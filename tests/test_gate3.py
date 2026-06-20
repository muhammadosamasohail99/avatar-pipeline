import json
from fastapi.testclient import TestClient
from pipeline.job_state import JobState

def test_gate3_pick(tmp_path, monkeypatch):
    monkeypatch.setattr("pipeline.job_state.JOBS_DIR", tmp_path)
    js = JobState.create("r", "T", "Selfie")
    sugg = [{"segment": {"start": 0, "end": 5, "text": "hi"},
             "options": [{"id": 1, "url": "u", "source": "pexels", "relevance": 0.9}],
             "picked": None}]
    (js.folder / "broll_suggestions.json").write_text(json.dumps(sugg))
    js.data["status"] = "gate_3"; js.save()
    from main import app
    c = TestClient(app)
    r = c.post(f"/jobs/{js.data['job_id']}/gate3/pick",
               data={"segment_index": "0", "option_index": "0"})
    assert r.status_code == 200
    saved = json.loads((js.folder / "broll_suggestions.json").read_text())
    assert saved[0]["picked"] == 0
