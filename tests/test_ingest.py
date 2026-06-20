from unittest.mock import MagicMock, patch
from pipeline.ingest import poll_once, detect_orphans, ALLOWED_FORMATS

def test_allowed_formats():
    assert "Selfie" in ALLOWED_FORMATS
    assert "Screen Recording" in ALLOWED_FORMATS
    assert "Split Screen" in ALLOWED_FORMATS

@patch("pipeline.ingest.Table")
def test_poll_picks_filming(mock_table, tmp_path, monkeypatch):
    monkeypatch.setattr("pipeline.ingest.JOBS_DIR", tmp_path)
    monkeypatch.setattr("pipeline.job_state.JOBS_DIR", tmp_path)
    inst = MagicMock()
    inst.all.return_value = [{
        "id": "rec1",
        "fields": {"Title": "T", "Hook 1": "H", "Script": "S", "Visual Format": "Selfie", "Pipeline Status": "Filming"},
    }]
    mock_table.return_value = inst
    jobs = poll_once()
    assert len(jobs) == 1
    inst.update.assert_called_with("rec1", {"Pipeline Status": "Processing"})
    assert (tmp_path / jobs[0].data["job_id"] / "job.json").exists()

@patch("pipeline.ingest.Table")
def test_detect_orphans(mock_table, tmp_path, monkeypatch):
    monkeypatch.setattr("pipeline.ingest.JOBS_DIR", tmp_path)
    monkeypatch.setattr("pipeline.job_state.JOBS_DIR", tmp_path)
    monkeypatch.setattr("pipeline.ingest.ActiveRegistry", MagicMock(all=lambda: {}))
    inst = MagicMock()
    inst.all.return_value = [{
        "id": "rec1",
        "fields": {"Title": "Orphan", "Pipeline Status": "Processing"},
    }]
    mock_table.return_value = inst
    orphans = detect_orphans()
    assert orphans == [("rec1", "Orphan")]
