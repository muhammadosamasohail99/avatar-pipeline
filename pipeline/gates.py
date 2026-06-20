import json
from config import PIPELINE
from pipeline.job_state import JobState
from modules.ffmpeg_utils import probe_video, get_audio_duration


def gate1_prechecks(js: JobState, audio_duration: float) -> list[dict]:
    script = (js.folder / "script.txt").read_text()
    words = len(script.split())
    expected = words / PIPELINE["wpm_target"] * 60
    tol = PIPELINE["duration_tolerance"]["gate1"]
    checks = []
    if expected == 0 or abs(audio_duration - expected) / expected > tol:
        checks.append({"id": "duration", "status": "warn",
                       "message": f"Audio {audio_duration:.1f}s vs expected {expected:.1f}s"})
    else:
        checks.append({"id": "duration", "status": "pass",
                       "message": f"Duration {audio_duration:.1f}s within ±{int(tol*100)}%"})
    align_path = js.folder / "voice_alignment.json"
    if align_path.exists():
        alignment = json.loads(align_path.read_text())
        from modules.elevenlabs_client import alignment_to_words
        ws = alignment_to_words(alignment)
        gaps = []
        for a, b in zip(ws, ws[1:]):
            if b["start"] - a["end"] > 2.0:
                gaps.append((a["end"], b["start"]))
        if gaps:
            checks.append({"id": "silence", "status": "warn",
                           "message": f"{len(gaps)} long silence gaps detected"})
        else:
            checks.append({"id": "silence", "status": "pass", "message": "No long mid-sentence silences"})
    return checks


def gate2_prechecks(js: JobState) -> list[dict]:
    v = js.folder / "avatar.mp4"
    a = js.folder / "voice.mp3"
    if not v.exists():
        return [{"id": "missing", "status": "warn", "message": "avatar.mp4 not present"}]
    info = probe_video(str(v))
    audio_dur = get_audio_duration(str(a)) if a.exists() else 0
    checks = []
    if info["height"] >= 1080:
        checks.append({"id": "resolution", "status": "pass",
                       "message": f"{info['width']}x{info['height']}"})
    else:
        checks.append({"id": "resolution", "status": "warn",
                       "message": f"{info['width']}x{info['height']} below 1080p"})
    tol = PIPELINE["duration_tolerance"]["gate2"]
    if abs(info["duration"] - audio_dur) / max(audio_dur, 0.1) <= tol:
        checks.append({"id": "duration", "status": "pass",
                       "message": f"Video {info['duration']:.1f}s matches audio"})
    else:
        checks.append({"id": "duration", "status": "warn",
                       "message": f"Drift {info['duration']:.1f}s vs {audio_dur:.1f}s"})
    if info["has_video"] and info["has_audio"]:
        checks.append({"id": "streams", "status": "pass", "message": "Streams OK"})
    else:
        checks.append({"id": "streams", "status": "warn", "message": "Missing stream"})
    return checks
