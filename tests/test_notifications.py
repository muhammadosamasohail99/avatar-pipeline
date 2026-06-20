from unittest.mock import patch
from pipeline.notifications import notify_macos, notify_all

@patch("pipeline.notifications.subprocess.run")
def test_macos(mock_run):
    notify_macos("Title", "Body")
    args = mock_run.call_args[0][0]
    assert args[0] == "osascript"
    assert "Title" in args[2]
    assert "Body" in args[2]

@patch("pipeline.notifications.subprocess.run")
@patch("pipeline.notifications.ingest_mod.mark_status")
def test_notify_all(mock_mark, mock_run):
    notify_all(record_id="rec1", airtable_status="Ready to Post",
               title="T", body="B")
    mock_mark.assert_called_with("rec1", "Ready to Post")
    mock_run.assert_called()
