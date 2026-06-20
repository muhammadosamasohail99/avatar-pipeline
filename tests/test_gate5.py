import json
from fastapi.testclient import TestClient
from pipeline.job_state import JobState

def test_flag_blocks_approve(tmp_path, monkeypatch):
    monkeypatch.setattr("pipeline.job_state.JOBS_DIR", tmp_path)
    js = JobState.create("r", "T", "Selfie")
    (js.folder / "composite.mp4").write_bytes(b"x")
    (js.folder / "voice.mp3").write_bytes(b"x")
    js.data["status"] = "gate_5"; js.save()
    from main import app
    c = TestClient(app)
    c.post(f"/jobs/{js.data['job_id']}/gate5/flag",
           data={"timestamp": "5.2", "reason": "Wrong B-roll"})
    flags = json.loads((js.folder / "gate5_flags.json").read_text())
    assert len(flags) == 1 and flags[0]["resolved"] is False
