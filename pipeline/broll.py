import json
import requests
from config import Settings, PIPELINE
from pipeline.job_state import JobState, ActiveRegistry
from pipeline.notifications import notify_all


def _pick_file(files: list[dict]) -> dict | None:
    hd = [f for f in files if f.get("quality") == "hd"]
    sd = [f for f in files if f.get("quality") == "sd"]
    pool = hd or sd or files
    if not pool:
        return None
    return min(pool, key=lambda f: abs((f.get("width") or 0) - 1280))


def pexels_search(query: str, per_page: int = 3) -> list[dict]:
    s = Settings()
    if not s.pexels_api_key:
        return []
    try:
        r = requests.get(
            "https://api.pexels.com/videos/search",
            headers={"Authorization": s.pexels_api_key},
            params={"query": query, "per_page": per_page, "size": "medium"},
            timeout=30,
        )
        r.raise_for_status()
    except Exception:
        return []
    results = []
    for v in r.json().get("videos", []):
        f = _pick_file(v.get("video_files", []))
        if not f:
            continue
        results.append({
            "url": f["link"],
            "thumbnail": v.get("image", ""),
            "source": "Pexels",
            "duration": v.get("duration", 0),
            "relevance": 0.75,
        })
    return results


def score_relevance(segment_text: str, query: str) -> float:
    seg = {w.lower() for w in segment_text.split() if len(w) > 3}
    qry = {w.lower() for w in query.split() if len(w) > 3}
    if not qry:
        return 0.5
    overlap = len(seg & qry)
    return round(min(1.0, 0.2 + (overlap / len(qry)) * 0.8), 2)


def transcode_to_cfr(src: str, dst: str) -> None:
    from modules.ffmpeg_utils import _run
    _run(["ffmpeg", "-y", "-i", src, "-r", "30",
          "-c:v", "libx264", "-preset", "fast", "-c:a", "aac",
          "-movflags", "+faststart", dst])


def _cache_clip_preview(cdn_url: str, local_path: str) -> bool:
    """Download clip via requests (Pexels CDN blocks FFmpeg's HTTP client),
    transcode first 10s to H.264 faststart for instant browser playback."""
    import requests as _req
    from pathlib import Path
    from modules.ffmpeg_utils import _run
    raw = Path(local_path).with_suffix(".raw.mp4")
    try:
        with _req.get(cdn_url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.pexels.com/"},
                      stream=True, timeout=60) as r:
            r.raise_for_status()
            with open(raw, "wb") as fh:
                for chunk in r.iter_content(65536):
                    fh.write(chunk)
        _run(["ffmpeg", "-y",
              "-i", str(raw),
              "-t", "10",
              "-c:v", "libx264", "-preset", "ultrafast", "-crf", "26",
              "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
              "-an",
              "-movflags", "+faststart",
              local_path])
        return True
    except Exception:
        return False
    finally:
        raw.unlink(missing_ok=True)


def _localize_options(options: list, seg_key: str, folder, job_id: str) -> list:
    """Replace CDN URLs with locally-cached faststart previews for reliable Gate 3 playback."""
    from pathlib import Path
    folder = Path(folder)
    for i, opt in enumerate(options):
        cdn_url = opt.get("url", "")
        if not cdn_url or not cdn_url.startswith("http"):
            continue
        fname = f"broll_preview_{seg_key}_{i}.mp4"
        local = folder / fname
        if not local.exists():
            _cache_clip_preview(cdn_url, str(local))
        if local.exists():
            opt["cdn_url"] = cdn_url  # preserved for full-quality assembly download
            opt["url"] = f"/jobs/{job_id}/broll/{fname}"
    return options


def segment_script(words: list[dict], hook_text: str = "") -> list[dict]:
    if not words:
        return []
    min_sec, max_sec = PIPELINE["broll_segment_window_sec"]
    segments: list[dict] = []
    seg_start = words[0]["start"]
    current: list[dict] = []
    for i, w in enumerate(words):
        current.append(w)
        duration = w["end"] - seg_start
        is_last = i == len(words) - 1
        has_pause = not is_last and (words[i + 1]["start"] - w["end"]) >= 0.1
        if duration >= max_sec or (duration >= min_sec and (has_pause or is_last)):
            segments.append({
                "start": seg_start,
                "end": w["end"],
                "text": " ".join(x["word"] for x in current),
                "is_hook": False,
            })
            seg_start = words[i + 1]["start"] if not is_last else w["end"]
            current = []
    if current:
        segments.append({
            "start": seg_start,
            "end": current[-1]["end"],
            "text": " ".join(x["word"] for x in current),
            "is_hook": False,
        })
    if hook_text and segments:
        segments[0]["is_hook"] = True
    return segments


def _gemini_query(segment_text: str) -> str:
    try:
        from modules.gemini_client import generate
        return generate(
            "Convert this video script excerpt into a 2-4 word Pexels stock video search query. "
            "Return ONLY the search query, nothing else.\n\n"
            f"Excerpt: {segment_text[:200]}"
        ).strip()[:80]
    except Exception:
        return segment_text[:80]


def _fetch_options(segment: dict, per_page: int = 3) -> list[dict]:
    query = _gemini_query(segment["text"])
    clips = pexels_search(query, per_page=per_page)
    for c in clips:
        c["relevance"] = score_relevance(segment["text"], query)
    return clips


def _cache_all_previews(suggestions: list, folder, job_id: str) -> None:
    """Cache faststart previews for all segments in a background thread.
    Updates broll_suggestions.json in-place as each segment completes."""
    import threading
    from pathlib import Path
    folder = Path(folder)

    def _worker():
        for i, s in enumerate(suggestions):
            opts = s.get("options")
            if not opts:
                continue
            seg_key = f"{s['segment']['start']:.2f}".replace(".", "_")
            cached = _localize_options([dict(o) for o in opts], seg_key, folder, job_id)
            # Re-read, patch this segment's options, write back
            try:
                sugg = json.loads((folder / "broll_suggestions.json").read_text())
                sugg[i]["options"] = cached
                (folder / "broll_suggestions.json").write_text(json.dumps(sugg, indent=2))
            except Exception:
                pass

    threading.Thread(target=_worker, daemon=True).start()


async def run_broll(js: JobState) -> None:
    ActiveRegistry.add(js.data["job_id"], "broll")
    try:
        js.set_stage("broll", "running")
        js.save()
        align_path = js.folder / "voice_alignment.json"
        if not align_path.exists():
            (js.folder / "broll_suggestions.json").write_text("[]")
            js.set_stage("broll", "done")
            js.data["status"] = "gate_3"
            js.save()
            return
        from modules.elevenlabs_client import alignment_to_words
        from pipeline.routing import plan_for_format
        alignment = json.loads(align_path.read_text())
        words = alignment_to_words(alignment)
        hook_text = (js.folder / "hook.txt").read_text() if (js.folder / "hook.txt").exists() else ""
        segments = segment_script(words, hook_text)
        broll_mode = plan_for_format(js.data["visual_format"])["broll_segments"]
        suggestions = []
        for i, seg in enumerate(segments):
            if broll_mode == "none":
                suggestions.append({"segment": seg, "options": [], "picked": "skip"})
            elif broll_mode == "intro_outro" and 0 < i < len(segments) - 1:
                suggestions.append({"segment": seg, "options": [], "picked": "skip"})
            else:
                opts = _fetch_options(seg)
                suggestions.append({"segment": seg, "options": opts, "picked": None})
        # Save with CDN URLs immediately so Gate 3 opens without waiting for preview caching
        (js.folder / "broll_suggestions.json").write_text(json.dumps(suggestions, indent=2))
        js.set_stage("broll", "done")
        js.data["status"] = "gate_3"
        js.save()
        notify_all("", "", "Avatar Pipeline", f"Gate 3 ready: {js.data['title']}")
        # Cache faststart previews in background — Gate 3 is already open with CDN URLs
        _cache_all_previews(suggestions, js.folder, js.data["job_id"])
    except Exception as exc:
        import traceback
        traceback.print_exc()
        js.data["status"] = "error"
        js.data["error"] = str(exc)
        js.data["error_gate"] = "2"
        js.save()
    finally:
        ActiveRegistry.remove(js.data["job_id"])
