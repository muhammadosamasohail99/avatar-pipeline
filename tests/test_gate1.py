from fastapi.testclient import TestClient
from pipeline.gates import gate1_prechecks
from pipeline.job_state import JobState

def test_prechecks_duration(tmp_path, monkeypatch):
    monkeypatch.setattr("pipeline.job_state.JOBS_DIR", tmp_path)
    js = JobState.create("rec1", "T", "Selfie")
    (js.folder / "script.txt").write_text(" ".join(["word"] * 100))
    checks = gate1_prechecks(js, audio_duration=37.5)
    dur = next(c for c in checks if c["id"] == "duration")
    assert dur["status"] == "pass"

def test_prechecks_duration_fail(tmp_path, monkeypatch):
    monkeypatch.setattr("pipeline.job_state.JOBS_DIR", tmp_path)
    js = JobState.create("rec1", "T", "Selfie")
    (js.folder / "script.txt").write_text(" ".join(["word"] * 100))
    checks = gate1_prechecks(js, audio_duration=10.0)
    dur = next(c for c in checks if c["id"] == "duration")
    assert dur["status"] == "warn"

def test_gate1_routes(tmp_path, monkeypatch):
    monkeypatch.setattr("pipeline.job_state.JOBS_DIR", tmp_path)
    js = JobState.create("rec1", "T", "Selfie")
    (js.folder / "voice.mp3").write_bytes(b"x")
    (js.folder / "script.txt").write_text("hi")
    js.data["status"] = "gate_1"; js.save()
    from main import app
    c = TestClient(app)
    r = c.get(f"/jobs/{js.data['job_id']}/gate1")
    assert r.status_code == 200
