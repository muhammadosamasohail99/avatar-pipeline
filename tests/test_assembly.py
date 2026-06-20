from unittest.mock import patch
from pipeline.assembly import assembly_prechecks
from pipeline.job_state import JobState

@patch("pipeline.assembly.probe_video")
def test_prechecks(mock_probe, tmp_path, monkeypatch):
    monkeypatch.setattr("pipeline.job_state.JOBS_DIR", tmp_path)
    js = JobState.create("r", "T", "Selfie")
    (js.folder / "composite.mp4").write_bytes(b"x")
    (js.folder / "voice.mp3").write_bytes(b"x")
    mock_probe.return_value = {"width": 1920, "height": 1080, "duration": 30.0,
                               "has_video": True, "has_audio": True}
    monkeypatch.setattr("pipeline.assembly.get_audio_duration", lambda p: 30.0)
    checks = assembly_prechecks(js)
    assert any(c["id"] == "duration" and c["status"] == "pass" for c in checks)
