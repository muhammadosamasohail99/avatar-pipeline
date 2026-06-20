from fastapi.testclient import TestClient
from pipeline.job_state import JobState

def test_gate6_view(tmp_path, monkeypatch):
    monkeypatch.setattr("pipeline.job_state.JOBS_DIR", tmp_path)
    js = JobState.create("r", "T", "Selfie")
    (js.folder / "final_16x9.mp4").write_bytes(b"x")
    (js.folder / "final_9x16.mp4").write_bytes(b"x")
    js.data["status"] = "gate_6"; js.save()
    from main import app
    c = TestClient(app)
    r = c.get(f"/jobs/{js.data['job_id']}/gate6")
    assert r.status_code == 200
