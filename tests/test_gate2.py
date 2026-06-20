from unittest.mock import patch
from pipeline.job_state import JobState

@patch("pipeline.gates.probe_video")
def test_gate2_prechecks_pass(mock_probe, tmp_path, monkeypatch):
    from pipeline.gates import gate2_prechecks
    monkeypatch.setattr("pipeline.job_state.JOBS_DIR", tmp_path)
    js = JobState.create("r", "T", "Selfie")
    (js.folder / "avatar.mp4").write_bytes(b"x")
    (js.folder / "voice.mp3").write_bytes(b"x")
    mock_probe.return_value = {"width": 1920, "height": 1080, "duration": 30.0,
                               "has_video": True, "has_audio": True}
    monkeypatch.setattr("pipeline.gates.get_audio_duration", lambda p: 30.0)
    checks = gate2_prechecks(js)
    assert all(c["status"] in ("pass", "warn") for c in checks)
    assert any(c["id"] == "resolution" and c["status"] == "pass" for c in checks)

def test_regen_cap(tmp_path, monkeypatch):
    monkeypatch.setattr("pipeline.job_state.JOBS_DIR", tmp_path)
    js = JobState.create("r", "T", "Selfie")
    for _ in range(5):
        js.bump_regen("avatar")
    assert js.data["regeneration_counts"]["avatar"] == 5
