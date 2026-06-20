import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from pipeline.recovery import resume_orphans, archive_old, next_resume_status
from pipeline.job_state import JobState

def test_next_status_from_stages():
    data = {"stages": {"voice": "done", "avatar": "done",
                       "broll": "pending", "assembly": "pending",
                       "export": "pending", "delivery": "pending"}}
    assert next_resume_status(data) == "gate_3"

def test_archive(tmp_path, monkeypatch):
    monkeypatch.setattr("pipeline.recovery.JOBS_DIR", tmp_path)
    monkeypatch.setattr("pipeline.recovery.ARCHIVE_DIR", tmp_path / "arch")
    (tmp_path / "arch").mkdir()
    j = tmp_path / "2025-01-01-old"; j.mkdir()
    (j / "job.json").write_text(json.dumps({
        "job_id": "2025-01-01-old", "status": "delivered",
        "created_at": (datetime.now(timezone.utc) - timedelta(days=45)).isoformat()
    }))
    archive_old(days=30)
    assert not j.exists()
    assert (tmp_path / "arch" / "2025-01-01-old").exists()

def test_resume_orphans(tmp_path, monkeypatch):
    monkeypatch.setattr("pipeline.recovery.JOBS_DIR", tmp_path)
    monkeypatch.setattr("pipeline.job_state.JOBS_DIR", tmp_path)
    from pipeline.job_state import ActiveRegistry
    monkeypatch.setattr("pipeline.recovery.ACTIVE_PATH", tmp_path / "active.json")
    monkeypatch.setattr("pipeline.job_state.ACTIVE_PATH", tmp_path / "active.json")
    js = JobState.create("r1", "T", "Selfie")
    js.set_stage("voice", "done"); js.save()
    ActiveRegistry.add(js.data["job_id"], "voice")
    resumed = resume_orphans()
    assert js.data["job_id"] in [r["job_id"] for r in resumed]
