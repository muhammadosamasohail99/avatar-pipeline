import json
from pathlib import Path
from pipeline.job_state import JobState, CostLedger, ActiveRegistry


def test_create_and_load(tmp_path, monkeypatch):
    monkeypatch.setattr("pipeline.job_state.JOBS_DIR", tmp_path)
    js = JobState.create("recABC", "Test Title", "Selfie")
    assert js.data["status"] == "ingested"
    assert js.data["cost_cap_usd"] == 15.0
    assert js.data["stages"]["voice"] == "pending"
    assert js.data["regeneration_counts"]["avatar"] == 0
    js.set_stage("voice", "done")
    js.save()
    js2 = JobState.load(js.data["job_id"])
    assert js2.data["stages"]["voice"] == "done"


def test_cost_increment(tmp_path, monkeypatch):
    monkeypatch.setattr("pipeline.job_state.JOBS_DIR", tmp_path)
    js = JobState.create("rec1", "X", "Selfie")
    js.add_cost("elevenlabs", 0.50)
    js.add_cost("heygen", 2.00)
    assert js.data["cost_usd"]["total"] == 2.50


def test_cost_cap_breach(tmp_path, monkeypatch):
    monkeypatch.setattr("pipeline.job_state.JOBS_DIR", tmp_path)
    js = JobState.create("rec1", "X", "Selfie")
    js.data["cost_cap_usd"] = 1.0
    js.save()
    try:
        js.add_cost("elevenlabs", 1.5)
        assert False, "should raise"
    except RuntimeError as e:
        assert "cost cap" in str(e).lower()


def test_active_registry(tmp_path, monkeypatch):
    monkeypatch.setattr("pipeline.job_state.ACTIVE_PATH", tmp_path / "active.json")
    ActiveRegistry.add("job-1", "voice")
    ActiveRegistry.add("job-2", "avatar")
    assert "job-1" in ActiveRegistry.all()
    ActiveRegistry.remove("job-1")
    assert "job-1" not in ActiveRegistry.all()


def test_slug_generation(tmp_path, monkeypatch):
    monkeypatch.setattr("pipeline.job_state.JOBS_DIR", tmp_path)
    js = JobState.create("rec1", "Hello World!!! 2026 -- AI / Tools", "Selfie")
    assert "hello-world" in js.data["job_id"]
    assert "/" not in js.data["job_id"]
