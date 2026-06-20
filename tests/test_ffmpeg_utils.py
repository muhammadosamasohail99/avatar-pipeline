import subprocess
from pathlib import Path
from modules.ffmpeg_utils import probe_video, extract_audio, loudnorm


def _make_silent_video(path: Path, seconds: int = 2):
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c=black:s=1920x1080:d={seconds}",
        "-f", "lavfi", "-i", f"sine=f=1000:d={seconds}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", str(path)
    ], check=True, capture_output=True)


def test_probe_video(tmp_path):
    f = tmp_path / "t.mp4"
    _make_silent_video(f)
    info = probe_video(str(f))
    assert info["width"] == 1920 and info["height"] == 1080
    assert info["duration"] >= 1.9
    assert info["has_audio"] is True
    assert info["has_video"] is True


def test_extract_audio(tmp_path):
    v = tmp_path / "v.mp4"
    a = tmp_path / "a.wav"
    _make_silent_video(v)
    extract_audio(str(v), str(a))
    assert a.exists() and a.stat().st_size > 0


def test_loudnorm(tmp_path):
    v = tmp_path / "in.mp4"
    out = tmp_path / "out.mp4"
    _make_silent_video(v)
    loudnorm(str(v), str(out), target_lufs=-14)
    assert out.exists()
