import json
from fastapi.testclient import TestClient
from pipeline.job_state import JobState

def test_gate4_edit(tmp_path, monkeypatch):
    monkeypatch.setattr("pipeline.job_state.JOBS_DIR", tmp_path)
    js = JobState.create("r", "T", "Selfie")
    phrases = [{"start": 0, "end": 1, "words": [{"word": "hi", "emphasis": False}]}]
    (js.folder / "phrases.json").write_text(json.dumps(phrases))
    js.data["status"] = "gate_4"; js.save()
    from main import app
    c = TestClient(app)
    r = c.post(f"/jobs/{js.data['job_id']}/gate4/toggle",
               data={"phrase_index": "0", "word_index": "0"})
    assert r.status_code == 200
    after = json.loads((js.folder / "phrases.json").read_text())
    assert after[0]["words"][0]["emphasis"] is True
