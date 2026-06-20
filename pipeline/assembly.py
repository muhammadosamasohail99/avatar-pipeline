import json
from pathlib import Path
from modules.ffmpeg_utils import composite_video, burn_captions, probe_video, get_audio_duration
from config import PIPELINE
from pipeline.job_state import JobState, ActiveRegistry

def assembly_prechecks(js: JobState) -> list[dict]:
    p = js.folder / "composite.mp4"
    if not p.exists():
        return [{"id": "missing", "status": "warn", "message": "composite.mp4 missing"}]
    info = probe_video(str(p))
    audio_dur = get_audio_duration(str(js.folder / "voice.mp3"))
    checks = []
    if abs(info["duration"] - audio_dur) <= PIPELINE["duration_tolerance"]["gate5"]:
        checks.append({"id": "duration", "status": "pass",
                       "message": f"Duration {info['duration']:.1f}s matches"})
    else:
        checks.append({"id": "duration", "status": "warn",
                       "message": f"Drift {info['duration']:.1f}s vs {audio_dur:.1f}s"})
    if info["has_video"] and info["has_audio"]:
        checks.append({"id": "streams", "status": "pass", "message": "AV streams OK"})
    return checks

async def run_assembly(js: JobState) -> None:
    ActiveRegistry.add(js.data["job_id"], "assembly")
    try:
        js.set_stage("assembly", "running"); js.save()
        suggestions = json.loads((js.folder / "broll_suggestions.json").read_text())

        # Only skip segments flagged "Wrong B-roll" (wrong content — needs replacement).
        # Technical flags ("B-roll not playing" etc.) are fixed by re-rendering; don't skip.
        flags_path = js.folder / "gate5_flags.json"
        wrong_times: set[float] = set()
        if flags_path.exists():
            for f in json.loads(flags_path.read_text()):
                if f.get("reason") == "Wrong B-roll" and not f.get("resolved"):
                    wrong_times.add(float(f["timestamp"]))

        broll = []
        for s in suggestions:
            pick = s.get("picked")
            if not (isinstance(pick, int) and pick < len(s["options"])):
                continue
            orig_start = s["segment"]["start"]
            orig_end = s["segment"]["end"]
            # Use custom timing if the user adjusted it, otherwise fall back to segment bounds
            seg_start = s["custom_start"] if s.get("custom_start") is not None else orig_start
            seg_end = s["custom_end"] if s.get("custom_end") is not None else orig_end
            # Skip if flagged as wrong B-roll (check against original segment bounds)
            if any(orig_start <= t <= orig_end for t in wrong_times):
                continue
            opt = s["options"][pick]
            # Custom uploads are stored locally; Pexels clips are cached by original start time
            if opt.get("source") == "Custom Upload":
                local = js.folder / Path(opt["url"]).name
            else:
                local = js.folder / f"broll_{orig_start:.2f}.mp4"
                if not local.exists():
                    # Prefer cdn_url (full quality) over url (may be a short local preview)
                    cdn = opt.get("cdn_url") or opt.get("url", "")
                    if cdn and cdn.startswith("http"):
                        import requests
                        raw = js.folder / f"broll_{orig_start:.2f}_raw.mp4"
                        with requests.get(cdn, stream=True, timeout=120) as r:
                            r.raise_for_status()
                            with open(raw, "wb") as fh:
                                for ch in r.iter_content(8192):
                                    fh.write(ch)
                        # Transcode to CFR H.264 — fixes VFR, HEVC, and fps mismatches
                        # that cause stills or 1-second clips in filter_complex
                        from pipeline.broll import transcode_to_cfr
                        transcode_to_cfr(str(raw), str(local))
                        raw.unlink(missing_ok=True)
            broll.append({"clip_path": str(local), "start": seg_start, "end": seg_end})

        # Clamp every clip's end to its actual duration so it never freezes on the last frame.
        broll.sort(key=lambda x: x["start"])
        for i, clip in enumerate(broll):
            try:
                clip_dur = probe_video(clip["clip_path"])["duration"]
                max_end = clip["start"] + clip_dur
                clip["end"] = min(clip["end"], max_end)
                # Also pull the next clip's end inward if it now overlaps
                if i + 1 < len(broll):
                    broll[i + 1]["start"] = max(broll[i + 1]["start"], clip["end"])
            except Exception:
                pass

        # No-captions composite — used by export to burn correct captions per format
        composite_video(str(js.folder / "avatar.mp4"), broll,
                        None,
                        str(js.folder / "composite_nocaps.mp4"))
        # Gate 5 preview: burn 16:9 captions on top
        ass = js.folder / "captions.ass"
        if ass.exists():
            burn_captions(str(js.folder / "composite_nocaps.mp4"),
                          str(ass),
                          str(js.folder / "composite.mp4"))
        else:
            import shutil
            shutil.copy(str(js.folder / "composite_nocaps.mp4"),
                        str(js.folder / "composite.mp4"))
        # Auto-resolve technical B-roll flags (not playing, shows as still, dimension mismatch)
        # now that re-render with faststart + letterbox has completed.
        _TECH_FLAGS = {"B-roll not playing", "B-roll shows as still", "Dimension mismatch"}
        flags_path = js.folder / "gate5_flags.json"
        if flags_path.exists():
            flags = json.loads(flags_path.read_text())
            changed = any(not f.get("resolved") and f.get("reason") in _TECH_FLAGS for f in flags)
            if changed:
                for f in flags:
                    if not f.get("resolved") and f.get("reason") in _TECH_FLAGS:
                        f["resolved"] = True
                flags_path.write_text(json.dumps(flags, indent=2))
        js.set_stage("assembly", "done")
        js.data["status"] = "gate_5"; js.save()
    except Exception as exc:
        import traceback
        traceback.print_exc()
        js.data["status"] = "error"
        js.data["error"] = str(exc)
        js.data["error_gate"] = "4"
        js.save()
    finally:
        ActiveRegistry.remove(js.data["job_id"])
