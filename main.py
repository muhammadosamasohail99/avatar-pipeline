import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Form, Request, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sse_starlette.sse import EventSourceResponse
from config import JOBS_DIR, PIPELINE, get_heygen_looks
from modules.ffmpeg_utils import get_audio_duration
from pipeline.gates import gate1_prechecks, gate2_prechecks
from pipeline.job_state import JobState
from workers.job_runner import JobRunner

templates = Jinja2Templates(directory="static")
runner = JobRunner(concurrency=PIPELINE["concurrency"])
_notifications: asyncio.Queue = asyncio.Queue()

async def _poll_loop():
    from pipeline.ingest import poll_once
    from pipeline.voice import run_voice
    interval = PIPELINE["poll_interval_sec"]
    while True:
        try:
            jobs = await asyncio.to_thread(poll_once)
            for js in jobs:
                print(f"[ingest] picked up: {js.data['job_id']}")
                await runner.submit(asyncio.to_thread(run_voice, js))
        except Exception:
            import traceback
            traceback.print_exc()
        await asyncio.sleep(interval)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from pipeline.recovery import resume_orphans, archive_old
    archive_old(days=PIPELINE["archive_days"])
    resumed = resume_orphans()
    for r in resumed:
        print(f"[recovery] resumed {r['job_id']} -> {r['status']}")
    await runner.start()
    # Recover stuck jobs after server restart
    for p in sorted(JOBS_DIR.glob("*/job.json")):
        try:
            js = JobState.load(p.parent.name)
            status = js.data["status"]
            if status == "ingested":
                if (js.folder / "voice.mp3").exists():
                    js.data["status"] = "gate_1"
                    js.data["stages"]["voice"] = "done"
                    js.save()
                    print(f"[recovery] ingested→gate_1: {js.data['job_id']}")
                else:
                    from pipeline.voice import run_voice
                    await runner.submit(asyncio.to_thread(run_voice, js))
                    print(f"[recovery] restart voice: {js.data['job_id']}")
            elif status == "avatar_running":
                mp4 = js.folder / "avatar.mp4"
                valid = False
                if mp4.exists():
                    try:
                        from modules.ffmpeg_utils import probe_video
                        probe_video(str(mp4))
                        valid = True
                    except Exception:
                        mp4.unlink(missing_ok=True)
                if valid:
                    js.data["status"] = "gate_2"
                    js.data["stages"]["avatar"] = "done"
                    js.save()
                    print(f"[recovery] avatar_running→gate_2: {js.data['job_id']}")
                else:
                    video_id = js.data.get("heygen_job_id")
                    if video_id:
                        from pipeline.avatar import resume_avatar_poll
                        await runner.submit(resume_avatar_poll(js))
                        print(f"[recovery] resume avatar poll: {js.data['job_id']}")
                    else:
                        js.data["status"] = "gate_1"
                        js.save()
                        print(f"[recovery] avatar_running→gate_1 (no job_id): {js.data['job_id']}")
            elif status == "voice_running":
                from pipeline.voice import run_voice
                await runner.submit(asyncio.to_thread(run_voice, js))
                print(f"[recovery] restart voice: {js.data['job_id']}")
            elif status == "broll_running":
                from pipeline.broll import run_broll
                await runner.submit(run_broll(js))
                print(f"[recovery] restart broll: {js.data['job_id']}")
            elif status == "captions_running":
                from pipeline.captions import run_captions
                await runner.submit(run_captions(js))
                print(f"[recovery] restart captions: {js.data['job_id']}")
            elif status == "assembly_running":
                from pipeline.assembly import run_assembly
                await runner.submit(run_assembly(js))
                print(f"[recovery] restart assembly: {js.data['job_id']}")
            elif status == "export_running":
                from pipeline.export import run_export
                await runner.submit(run_export(js))
                print(f"[recovery] restart export: {js.data['job_id']}")
            elif status == "delivering":
                from pipeline.export import run_delivery
                await runner.submit(run_delivery(js))
                print(f"[recovery] restart delivery: {js.data['job_id']}")
        except Exception:
            import traceback
            traceback.print_exc()
    poll_task = asyncio.create_task(_poll_loop())
    yield
    poll_task.cancel()
    await runner.stop()

app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")

def _job_href(j: dict) -> str:
    status = j.get("status", "")
    if status.startswith("gate_"):
        return f"/jobs/{j['job_id']}/{status.replace('_', '')}"
    return f"/jobs/{j['job_id']}"


def list_jobs() -> list[dict]:
    out = []
    for p in sorted(JOBS_DIR.glob("*/job.json"), reverse=True):
        try:
            out.append(json.loads(p.read_text()))
        except Exception:
            pass
    return out

@app.get("/health")
def health():
    return {"ok": True}

@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    return templates.TemplateResponse(
        request, "index.html", {"jobs": list_jobs()})

@app.get("/events")
async def events(request: Request):
    async def gen():
        last_state = ""
        while True:
            if await request.is_disconnected():
                break
            jobs = list_jobs()
            state = json.dumps([(j["job_id"], j["status"]) for j in jobs])
            if state != last_state:
                rows = "".join(
                    f'<tr><td>{j["title"]}</td><td>{j["visual_format"]}</td>'
                    f'<td><span class="badge">{j["status"]}</span></td>'
                    f'<td><a href="{_job_href(j)}">Open</a></td></tr>'
                    for j in jobs
                )
                yield {"event": "jobs", "data": rows}
                last_state = state
            try:
                msg = await asyncio.wait_for(_notifications.get(), timeout=2.0)
                yield {"event": "notify", "data": msg}
            except asyncio.TimeoutError:
                pass
    return EventSourceResponse(gen())

async def notify(message: str) -> None:
    await _notifications.put(message)


_STATUS_MESSAGES = {
    #                    message                                         poll  typical
    "ingested":         ("Queued — waiting to generate voice…",          20,  "< 1 min"),
    "voice_running":    ("Generating voice with ElevenLabs…",            10,  "30–60 sec"),
    "avatar_running":   ("Generating avatar with HeyGen…",               30,  "5–15 min"),
    "broll_running":    ("Sourcing B-roll from Pexels…",                 10,  "1–2 min"),
    "captions_running": ("Analysing & grouping captions…",               10,  "30–60 sec"),
    "assembly_running": ("Assembling video with FFmpeg…",                10,  "1–3 min"),
    "export_running":   ("Exporting 16:9 + 9:16…",                      15,  "2–5 min"),
    "delivering":       ("Uploading to Dropbox…",                        10,  "1–5 min"),
}
_GATE_LABELS = {
    "1": "Gate 1 — Audio ready",
    "2": "Gate 2 — Avatar ready",
    "3": "Gate 3 — B-roll ready",
    "4": "Gate 4 — Captions ready",
    "5": "Gate 5 — Composite ready",
    "6": "Gate 6 — Final export ready",
}


_GATE_BACK: dict[str, tuple[str, list[str]]] = {
    "2": ("gate_1", ["avatar", "broll", "captions", "assembly", "export", "delivery"]),
    "3": ("gate_2", ["broll", "captions", "assembly", "export", "delivery"]),
    "4": ("gate_3", ["captions", "assembly", "export", "delivery"]),
    "5": ("gate_4", ["assembly", "export", "delivery"]),
    "6": ("gate_5", ["export", "delivery"]),
}


@app.post("/jobs/{job_id}/gate{gate_num}/back", response_class=HTMLResponse)
def gate_back(job_id: str, gate_num: str):
    if gate_num not in _GATE_BACK:
        return HTMLResponse("", headers={"HX-Redirect": f"/jobs/{job_id}"})
    prev_status, reset_stages = _GATE_BACK[gate_num]
    js = JobState.load(job_id)
    js.data["status"] = prev_status
    for stage in reset_stages:
        js.data["stages"][stage] = "pending"
    js.save()
    prev_gate_path = prev_status.replace("_", "")  # gate_1 → gate1
    return HTMLResponse("", headers={"HX-Redirect": f"/jobs/{job_id}/{prev_gate_path}"})


def _status_card(job_id: str, message: str, poll_secs: int = 15,
                 typical: str = "") -> HTMLResponse:
    typical_html = (
        f'<span style="color:var(--body)">Typically {typical}</span> · '
        if typical else ""
    )
    html = (
        f'<div class="card status-running" id="status-card"'
        f' hx-get="/jobs/{job_id}/status-fragment"'
        f' hx-trigger="every {poll_secs}s" hx-swap="outerHTML">'
        f'<div class="progress-wrap"><div class="progress-sweep"></div></div>'
        f'<div class="status-row">'
        f'<div class="spinner"></div>'
        f'<div>'
        f'<strong>{message}</strong>'
        f'<div style="font-size:13px;margin-top:4px">'
        f'{typical_html}'
        f'<span id="sc-elapsed">0:00</span> elapsed'
        f'</div>'
        f'</div></div>'
        f'</div>'
    )
    return HTMLResponse(html)


def _gate_redirect(job_id: str) -> HTMLResponse:
    """After gate approval, redirect to the job status page (has ← Dashboard link)."""
    return HTMLResponse("", headers={"HX-Redirect": f"/jobs/{job_id}"})


@app.get("/jobs/{job_id}/status-fragment", response_class=HTMLResponse)
def status_fragment(job_id: str):
    js = JobState.load(job_id)
    status = js.data["status"]
    if status.startswith("gate_"):
        gate_num = status.split("_")[1]
        label = _GATE_LABELS.get(gate_num, f"Gate {gate_num} ready")
        return HTMLResponse(
            f'<div class="card status-done" id="status-card">'
            f'<p style="margin:0">✅ <strong>{label}</strong> — '
            f'<a href="/jobs/{job_id}/gate{gate_num}">Open Gate {gate_num} →</a></p>'
            f'</div>'
        )
    if status == "delivered":
        delivered = js.data.get("delivered_formats", [])
        skipped  = js.data.get("skipped_formats", [])
        fmt_line = " + ".join(delivered) if delivered else "nothing"
        skip_line = (f'<br><small style="color:#c33">⚠️ Missing (not uploaded): {", ".join(skipped)}</small>'
                     if skipped else "")
        return HTMLResponse(
            f'<div class="card status-done" id="status-card">'
            f'<p style="margin:0">✅ <strong>Delivered to Dropbox</strong> — {fmt_line}{skip_line}</p>'
            f'</div>'
        )
    if status == "paused_edit":
        return HTMLResponse(
            f'<div class="card" id="status-card">'
            f'<p style="margin:0">✏️ <strong>Paused for script edit.</strong><br>'
            f'<small style="color:var(--body)">If you paused accidentally, click Resume to go back to Gate 1.</small></p>'
            f'<form method="post" action="/jobs/{job_id}/unpause" style="margin-top:12px">'
            f'<button type="submit" class="secondary">Resume → Gate 1</button>'
            f'</form>'
            f'</div>'
        )
    if status == "error":
        err = js.data.get("error", "Unknown error")
        gate = js.data.get("error_gate", "")
        back_link = (
            f'<a href="/jobs/{job_id}/gate{gate}" style="display:inline-block;margin-top:10px;'
            f'padding:8px 16px;background:var(--accent);color:white;border-radius:6px;'
            f'text-decoration:none;font-size:13px">← Return to Gate {gate}</a>'
            if gate else
            f'<a href="/" style="display:inline-block;margin-top:10px;'
            f'padding:8px 16px;background:var(--accent);color:white;border-radius:6px;'
            f'text-decoration:none;font-size:13px">← Dashboard</a>'
        )
        return HTMLResponse(
            f'<div class="card" id="status-card" style="border-left:3px solid #c33">'
            f'<p style="margin:0">❌ <strong>Stage failed</strong><br>'
            f'<small style="color:#c33;word-break:break-word">{err}</small></p>'
            f'{back_link}</div>'
        )
    entry = _STATUS_MESSAGES.get(status, (f"Running: {status}", 15, ""))
    msg, poll, typical = entry if len(entry) == 3 else (*entry, "")
    # Append per-file delivery note if present
    note = js.data.get("delivery_note", "")
    if note:
        msg = f"{msg} <small style='color:var(--body)'>({note})</small>"
    return _status_card(job_id, msg, poll, typical)


@app.get("/jobs/{job_id}", response_class=HTMLResponse)
def job_detail(request: Request, job_id: str):
    js = JobState.load(job_id)
    status = js.data["status"]
    if status.startswith("gate_"):
        return RedirectResponse(f"/jobs/{job_id}/{status.replace('_', '')}")
    return templates.TemplateResponse(request, "job_status.html", {"job": js.data})


@app.get("/jobs/{job_id}/file/{name}")
def job_file(job_id: str, name: str):
    return FileResponse(JOBS_DIR / job_id / name)


@app.get("/jobs/{job_id}/gate1", response_class=HTMLResponse)
def gate1_view(request: Request, job_id: str):
    js = JobState.load(job_id)
    try:
        dur = get_audio_duration(str(js.folder / "voice.mp3")) if (js.folder / "voice.mp3").exists() else 0
    except Exception:
        dur = 0
    checks = gate1_prechecks(js, dur)
    return templates.TemplateResponse(request, "gates/gate1.html", {
        "job": js.data, "checks": checks,
        "script": (js.folder / "script.txt").read_text() if (js.folder / "script.txt").exists() else "",
        "looks": get_heygen_looks(),
    })


@app.post("/jobs/{job_id}/gate1/decision", response_class=HTMLResponse)
async def gate1_decide(request: Request, job_id: str, action: str = Form(...),
                       look_avatar_id: str = Form(default="")):
    js = JobState.load(job_id)
    if look_avatar_id:
        js.data["look_avatar_id"] = look_avatar_id
    js.set_gate("gate1", action)
    if action == "approve":
        js.data["status"] = "avatar_running"
        js.save()
        from pipeline.avatar import run_avatar
        await runner.submit(run_avatar(js))
        return _gate_redirect(job_id)
    if action == "regenerate":
        js.bump_regen("voice")
        js.data["status"] = "voice_running"
        js.save()
        from pipeline.voice import run_voice
        await runner.submit(asyncio.to_thread(run_voice, js))
        return _gate_redirect(job_id)
    if action == "edit":
        from pipeline import ingest as ingest_mod
        ingest_mod.mark_status(js.data["airtable_record_id"], "Scripted")
        js.data["status"] = "paused_edit"
        js.save()
        return HTMLResponse("<p>Job paused — Airtable status set to Scripted for re-editing.</p>")


@app.post("/jobs/{job_id}/unpause")
def job_unpause(job_id: str):
    """Resume a paused_edit job back to gate_1 without touching Airtable."""
    js = JobState.load(job_id)
    if js.data.get("status") == "paused_edit":
        js.data["status"] = "gate_1"
        js.save()
    return RedirectResponse(f"/jobs/{job_id}/gate1", status_code=303)


@app.get("/jobs/{job_id}/gate2", response_class=HTMLResponse)
def gate2_view(request: Request, job_id: str):
    js = JobState.load(job_id)
    return templates.TemplateResponse(request, "gates/gate2.html", {
        "job": js.data, "checks": gate2_prechecks(js),
    })


@app.post("/jobs/{job_id}/gate2/decision", response_class=HTMLResponse)
async def gate2_decide(job_id: str, action: str = Form(...)):
    js = JobState.load(job_id)
    js.set_gate("gate2", action)
    if action == "approve":
        js.data["status"] = "broll_running"; js.save()
        from pipeline.broll import run_broll
        await runner.submit(run_broll(js))
        return _gate_redirect(job_id)
    if action in ("regenerate", "override"):
        js.bump_regen("avatar")
        js.data["status"] = "avatar_running"; js.save()
        from pipeline.avatar import run_avatar
        await runner.submit(run_avatar(js))
        return _gate_redirect(job_id)


import json as _json
from fastapi import UploadFile, File

_BROLL_FLAG_REASONS = {"Wrong B-roll", "B-roll not playing", "B-roll shows as still", "Dimension mismatch"}

def _seg_normalize(s: dict) -> dict:
    s = dict(s)
    s.setdefault("custom_start", None)
    s.setdefault("custom_end", None)
    s.setdefault("flagged", False)
    return s

def _seg_card(request: Request, js: JobState, sugg: list, idx: int):
    s = _seg_normalize(sugg[idx])
    return templates.TemplateResponse(
        request, "gates/gate3_card.html",
        {"job": js.data, "s": s, "idx": idx}
    )

def _sugg_save(js: JobState, sugg: list) -> None:
    (js.folder / "broll_suggestions.json").write_text(_json.dumps(sugg, indent=2))

@app.get("/jobs/{job_id}/gate3", response_class=HTMLResponse)
def gate3_view(request: Request, job_id: str):
    js = JobState.load(job_id)
    sugg = _json.loads((js.folder / "broll_suggestions.json").read_text())
    # Mark segments flagged "Wrong B-roll" — these need a replacement clip picked in Gate 3.
    # Technical flags (not playing, dimension mismatch) are fixed by re-rendering, not Gate 3.
    fp = js.folder / "gate5_flags.json"
    wrong_times: set[float] = set()
    if fp.exists():
        for f in _json.loads(fp.read_text()):
            if f.get("reason") == "Wrong B-roll" and not f.get("resolved"):
                wrong_times.add(float(f["timestamp"]))
    for s in sugg:
        seg = s["segment"]
        s["flagged"] = any(seg["start"] <= t <= seg["end"] for t in wrong_times)
    sugg = [_seg_normalize(s) for s in sugg]
    return templates.TemplateResponse(request, "gates/gate3.html",
        {"job": js.data, "suggestions": sugg})

@app.get("/jobs/{job_id}/broll/{filename}", response_class=HTMLResponse)
def serve_broll_file(job_id: str, filename: str):
    from fastapi.responses import FileResponse
    js = JobState.load(job_id)
    path = js.folder / filename
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404)
    return FileResponse(str(path))

@app.post("/jobs/{job_id}/gate3/pick", response_class=HTMLResponse)
def gate3_pick(request: Request, job_id: str, segment_index: int = Form(...), option_index: int = Form(...)):
    js = JobState.load(job_id)
    sugg = _json.loads((js.folder / "broll_suggestions.json").read_text())
    sugg[segment_index]["picked"] = option_index
    # Always write explicit timestamps so the timing form shows what will actually be used.
    # If the clip is shorter than the window, clamp end so the clip never freezes on its last frame.
    s = sugg[segment_index]
    opt = s["options"][option_index]
    seg_start = s["custom_start"] if s.get("custom_start") is not None else s["segment"]["start"]
    seg_end   = s["custom_end"]   if s.get("custom_end")   is not None else s["segment"]["end"]
    clip_dur  = opt.get("duration") or 0
    if clip_dur > 0:
        seg_end = min(seg_end, round(seg_start + clip_dur, 2))
    sugg[segment_index]["custom_start"] = round(seg_start, 2)
    sugg[segment_index]["custom_end"]   = round(seg_end,   2)
    _sugg_save(js, sugg)
    return _seg_card(request, js, sugg, segment_index)

@app.post("/jobs/{job_id}/gate3/unpick", response_class=HTMLResponse)
def gate3_unpick(request: Request, job_id: str, segment_index: int = Form(...)):
    js = JobState.load(job_id)
    sugg = _json.loads((js.folder / "broll_suggestions.json").read_text())
    sugg[segment_index]["picked"] = None
    _sugg_save(js, sugg)
    return _seg_card(request, js, sugg, segment_index)

@app.post("/jobs/{job_id}/gate3/refresh", response_class=HTMLResponse)
async def gate3_refresh(request: Request, job_id: str, segment_index: int = Form(...)):
    js = JobState.load(job_id)
    sugg = _json.loads((js.folder / "broll_suggestions.json").read_text())
    seg = sugg[segment_index]["segment"]
    from pipeline.broll import _gemini_query, pexels_search, score_relevance
    query = _gemini_query(seg["text"])
    new_opts = pexels_search(query, per_page=3)
    for opt in new_opts:
        opt["relevance"] = score_relevance(seg["text"], query)
    seg_key = f"{seg['start']:.2f}".replace(".", "_")
    # Remove stale previews
    for old in js.folder.glob(f"broll_preview_{seg_key}_*.mp4"):
        old.unlink(missing_ok=True)
    # Save immediately with CDN URLs so the response is instant.
    # Browsers can play CDN <video> tags directly; faststart previews are cached in the background.
    sugg[segment_index]["options"] = new_opts
    sugg[segment_index]["picked"] = None
    _sugg_save(js, sugg)

    # Background task: download + transcode previews, then update suggestions
    folder = js.folder
    job_id_str = js.data["job_id"]

    async def _cache_previews_bg():
        try:
            from pipeline.broll import _localize_options
            opts_copy = [dict(o) for o in new_opts]
            cached = await asyncio.to_thread(
                _localize_options, opts_copy, seg_key, folder, job_id_str
            )
            latest = _json.loads((folder / "broll_suggestions.json").read_text())
            latest[segment_index]["options"] = cached
            (folder / "broll_suggestions.json").write_text(_json.dumps(latest, indent=2))
        except Exception:
            pass

    asyncio.create_task(_cache_previews_bg())
    return _seg_card(request, js, sugg, segment_index)

@app.post("/jobs/{job_id}/gate3/skip", response_class=HTMLResponse)
def gate3_skip(request: Request, job_id: str, segment_index: int = Form(...)):
    js = JobState.load(job_id)
    sugg = _json.loads((js.folder / "broll_suggestions.json").read_text())
    sugg[segment_index]["picked"] = "skip"
    _sugg_save(js, sugg)
    return _seg_card(request, js, sugg, segment_index)

@app.post("/jobs/{job_id}/gate3/timing", response_class=HTMLResponse)
def gate3_timing(request: Request, job_id: str, segment_index: int = Form(...),
                 custom_start: float = Form(...), custom_end: float = Form(...)):
    js = JobState.load(job_id)
    sugg = _json.loads((js.folder / "broll_suggestions.json").read_text())
    sugg[segment_index]["custom_start"] = round(custom_start, 2)
    sugg[segment_index]["custom_end"]   = round(custom_end,   2)
    # Cascade: previous segment's end = this segment's start
    if segment_index > 0:
        sugg[segment_index - 1]["custom_end"]   = round(custom_start, 2)
    # Cascade: next segment's start = this segment's end
    if segment_index < len(sugg) - 1:
        sugg[segment_index + 1]["custom_start"] = round(custom_end, 2)
    _sugg_save(js, sugg)
    # Render current card + OOB swaps for the adjacent cards that changed
    tmpl = templates.env.get_template("gates/gate3_card.html")
    def _render(i: int) -> str:
        return tmpl.render(job=js.data, s=_seg_normalize(sugg[i]), idx=i)
    html = _render(segment_index)
    if segment_index > 0:
        prev = _render(segment_index - 1)
        html += prev.replace(f'id="seg-{segment_index - 1}"',
                             f'id="seg-{segment_index - 1}" hx-swap-oob="true"', 1)
    if segment_index < len(sugg) - 1:
        nxt = _render(segment_index + 1)
        html += nxt.replace(f'id="seg-{segment_index + 1}"',
                            f'id="seg-{segment_index + 1}" hx-swap-oob="true"', 1)
    return HTMLResponse(html)

@app.post("/jobs/{job_id}/gate3/upload-segment", response_class=HTMLResponse)
async def gate3_upload_segment(request: Request, job_id: str,
                                segment_index: int = Form(...), file: UploadFile = File(...)):
    js = JobState.load(job_id)
    sugg = _json.loads((js.folder / "broll_suggestions.json").read_text())
    suffix = Path(file.filename).suffix or ".mp4"
    raw = js.folder / f"broll_custom_{segment_index}_raw{suffix}"
    raw.write_bytes(await file.read())
    from pipeline.broll import transcode_to_cfr
    out = js.folder / f"broll_custom_{segment_index}.mp4"
    transcode_to_cfr(str(raw), str(out))
    raw.unlink(missing_ok=True)
    serve_url = f"/jobs/{job_id}/broll/broll_custom_{segment_index}.mp4"
    # Probe duration so pick-time clamping works for custom uploads too
    try:
        from modules.ffmpeg_utils import probe_video
        upload_dur = probe_video(str(out))["duration"]
    except Exception:
        upload_dur = None
    custom_opt = {"url": serve_url, "source": "Custom Upload", "relevance": 1.0, "duration": upload_dur}
    sugg[segment_index]["options"].insert(0, custom_opt)
    sugg[segment_index]["picked"] = 0
    # Clamp end time to clip duration
    s = sugg[segment_index]
    if upload_dur and upload_dur > 0:
        seg_start = s["custom_start"] if s.get("custom_start") is not None else s["segment"]["start"]
        seg_end   = s["custom_end"]   if s.get("custom_end")   is not None else s["segment"]["end"]
        max_end = round(seg_start + upload_dur, 2)
        if seg_end > max_end:
            sugg[segment_index]["custom_end"] = max_end
    _sugg_save(js, sugg)
    return _seg_card(request, js, sugg, segment_index)

@app.post("/jobs/{job_id}/gate3/upload", response_class=HTMLResponse)
async def gate3_upload(job_id: str, file: UploadFile = File(...)):
    js = JobState.load(job_id)
    raw = js.folder / f"screen_raw{Path(file.filename).suffix}"
    raw.write_bytes(await file.read())
    from pipeline.broll import transcode_to_cfr
    out = js.folder / "screen.mp4"
    transcode_to_cfr(str(raw), str(out))
    return HTMLResponse("<p>Screen recording uploaded + transcoded.</p>")

@app.post("/jobs/{job_id}/gate3/done", response_class=HTMLResponse)
async def gate3_done(job_id: str):
    js = JobState.load(job_id)
    # Resolve "Wrong B-roll" flags — user has picked replacement clips in Gate 3.
    # Technical flags resolve automatically when assembly succeeds.
    fp = js.folder / "gate5_flags.json"
    if fp.exists():
        flags = _json.loads(fp.read_text())
        changed = False
        for f in flags:
            if f.get("reason") == "Wrong B-roll" and not f.get("resolved"):
                f["resolved"] = True
                changed = True
        if changed:
            fp.write_text(_json.dumps(flags, indent=2))
    js.set_gate("gate3", "approve")
    js.data["status"] = "captions_running"; js.save()
    from pipeline.captions import run_captions
    await runner.submit(run_captions(js))
    return _gate_redirect(job_id)

@app.get("/jobs/{job_id}/gate4", response_class=HTMLResponse)
def gate4_view(request: Request, job_id: str):
    js = JobState.load(job_id)
    phrases = _json.loads((js.folder / "phrases.json").read_text())
    return templates.TemplateResponse(request, "gates/gate4.html",
        {"job": js.data, "phrases": phrases})

@app.post("/jobs/{job_id}/gate4/toggle", response_class=HTMLResponse)
def gate4_toggle(job_id: str, phrase_index: int = Form(...), word_index: int = Form(...)):
    js = JobState.load(job_id)
    p = js.folder / "phrases.json"
    phrases = _json.loads(p.read_text())
    w = phrases[phrase_index]["words"][word_index]
    w["emphasis"] = not w.get("emphasis", False)
    p.write_text(_json.dumps(phrases, indent=2))
    return HTMLResponse("")

@app.post("/jobs/{job_id}/gate4/reanalyze", response_class=HTMLResponse)
async def gate4_reanalyze(job_id: str):
    """Re-run emphasis detection (rule + Gemini) on current phrases without regrouping."""
    js = JobState.load(job_id)
    from modules.elevenlabs_client import alignment_to_words
    from pipeline.captions import assign_emphasis, render_preview
    # Re-run emphasis on the flat word list
    alignment = _json.loads((js.folder / "voice_alignment.json").read_text())
    words = alignment_to_words(alignment)
    script = (js.folder / "script.txt").read_text() if (js.folder / "script.txt").exists() else ""
    assign_emphasis(script, words)
    # Apply updated emphasis back onto existing phrase grouping by flat index
    phrases_path = js.folder / "phrases.json"
    phrases = _json.loads(phrases_path.read_text())
    flat_idx = 0
    for phrase in phrases:
        for word in phrase["words"]:
            word["emphasis"] = words[flat_idx]["emphasis"] if flat_idx < len(words) else False
            flat_idx += 1
    phrases_path.write_text(_json.dumps(phrases, indent=2))
    # Update ASS files so Re-render preview picks up the new emphasis — no video burn yet
    from modules.ass_writer import write_ass
    write_ass(str(js.folder / "captions.ass"), phrases,
              margin_v=PIPELINE["caption"]["margin_v_16x9"],
              play_res_x=1920, play_res_y=1080,
              fontsize=PIPELINE["caption"]["fontsize"])
    write_ass(str(js.folder / "captions_9x16.ass"), phrases,
              margin_v=PIPELINE["caption"]["margin_v_9x16"],
              play_res_x=1080, play_res_y=1920,
              fontsize=PIPELINE["caption"]["fontsize_9x16"])
    return HTMLResponse("", headers={"HX-Refresh": "true"})

@app.post("/jobs/{job_id}/gate4/decision", response_class=HTMLResponse)
async def gate4_decide(job_id: str, action: str = Form(...)):
    js = JobState.load(job_id)
    if action == "rerender":
        phrases = _json.loads((js.folder / "phrases.json").read_text())
        from modules.ass_writer import write_ass
        from pipeline.captions import render_preview
        write_ass(str(js.folder / "captions.ass"), phrases,
                  margin_v=PIPELINE["caption"]["margin_v_16x9"],
                  play_res_x=1920, play_res_y=1080,
                  fontsize=PIPELINE["caption"]["fontsize"])
        write_ass(str(js.folder / "captions_9x16.ass"), phrases,
                  margin_v=PIPELINE["caption"]["margin_v_9x16"],
                  play_res_x=1080, play_res_y=1920,
                  fontsize=PIPELINE["caption"]["fontsize_9x16"])
        render_preview(str(js.folder / "avatar.mp4"),
                       str(js.folder / "captions.ass"),
                       str(js.folder / "preview_captions.mp4"))
        return HTMLResponse("", headers={"HX-Refresh": "true"})
    js.set_gate("gate4", "approve")
    js.data["status"] = "assembly_running"; js.save()
    from pipeline.assembly import run_assembly
    await runner.submit(run_assembly(js))
    return _gate_redirect(job_id)

from pipeline.assembly import assembly_prechecks

@app.get("/jobs/{job_id}/gate5", response_class=HTMLResponse)
def gate5_view(request: Request, job_id: str):
    js = JobState.load(job_id)
    fp = js.folder / "gate5_flags.json"
    flags = _json.loads(fp.read_text()) if fp.exists() else []
    unresolved = any(not f.get("resolved") for f in flags)
    # Amber Gate 3 redirect only for "Wrong B-roll" (wrong clip content).
    # Technical flags ("B-roll not playing" etc.) are resolved by re-rendering.
    has_wrong_broll = any(
        not f.get("resolved") and f.get("reason") == "Wrong B-roll" for f in flags
    )
    return templates.TemplateResponse(request, "gates/gate5.html", {
        "job": js.data,
        "checks": assembly_prechecks(js), "flags": flags,
        "unresolved": unresolved, "has_wrong_broll": has_wrong_broll,
    })

@app.post("/jobs/{job_id}/gate5/flag", response_class=HTMLResponse)
def gate5_flag(job_id: str, timestamp: str = Form(...), reason: str = Form(...)):
    js = JobState.load(job_id)
    fp = js.folder / "gate5_flags.json"
    flags = _json.loads(fp.read_text()) if fp.exists() else []
    idx = len(flags)
    flags.append({"timestamp": float(timestamp), "reason": reason, "resolved": False})
    fp.write_text(_json.dumps(flags, indent=2))
    return HTMLResponse(
        f'<li id="flag-{idx}">{timestamp}s — {reason} '
        f'<button hx-post="/jobs/{job_id}/gate5/resolve" '
        f'hx-vals=\'{{"flag_index":"{idx}"}}\' '
        f'hx-target="#flag-{idx}" hx-swap="outerHTML" '
        f'class="secondary" style="font-size:11px;padding:2px 8px;margin-left:6px">✓ Resolve</button>'
        f'</li>'
    )

@app.post("/jobs/{job_id}/gate5/resolve", response_class=HTMLResponse)
def gate5_resolve(job_id: str, flag_index: int = Form(...)):
    js = JobState.load(job_id)
    fp = js.folder / "gate5_flags.json"
    flags = _json.loads(fp.read_text()) if fp.exists() else []
    if 0 <= flag_index < len(flags):
        flags[flag_index]["resolved"] = True
        fp.write_text(_json.dumps(flags, indent=2))
        f = flags[flag_index]
        return HTMLResponse(
            f'<li id="flag-{flag_index}" style="color:gray;text-decoration:line-through">'
            f'{f["timestamp"]}s — {f["reason"]} ✓</li>'
        )
    return HTMLResponse("")

@app.post("/jobs/{job_id}/gate5/decision", response_class=HTMLResponse)
async def gate5_decide(job_id: str, action: str = Form("approve")):
    js = JobState.load(job_id)
    if action == "rerender":
        from pipeline.assembly import run_assembly
        await runner.submit(run_assembly(js))
        return _gate_redirect(job_id)
    js.set_gate("gate5", "approve")
    js.data["status"] = "export_running"; js.save()
    from pipeline.export import run_export
    await runner.submit(run_export(js))
    return _gate_redirect(job_id)

from pipeline.export import export_prechecks

@app.get("/jobs/{job_id}/gate6", response_class=HTMLResponse)
def gate6_view(request: Request, job_id: str):
    js = JobState.load(job_id)
    return templates.TemplateResponse(request, "gates/gate6.html",
        {"job": js.data, "checks": export_prechecks(js)})

@app.post("/jobs/{job_id}/gate6/decision", response_class=HTMLResponse)
async def gate6_decide(job_id: str):
    js = JobState.load(job_id)
    js.set_gate("gate6", "approve")
    js.data["status"] = "delivering"; js.save()
    from pipeline.export import run_delivery
    await runner.submit(run_delivery(js))
    return _gate_redirect(job_id)
