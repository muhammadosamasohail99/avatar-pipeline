from unittest.mock import patch, MagicMock
from pipeline.export import slug_filename, deliver_dropbox
from pipeline.job_state import JobState

def test_slug():
    assert slug_filename("Hello World!", "16x9", "2026-05-16") == "2026-05-16-hello-world-16x9.mp4"
    assert slug_filename("Café — émoji 🚀", "9x16", "2026-05-16").startswith("2026-05-16-")
    assert len(slug_filename("a" * 200, "16x9", "2026-05-16").rsplit("-16x9", 1)[0]) <= 80

@patch("pipeline.export.dropbox.Dropbox")
def test_deliver(mock_db, tmp_path):
    inst = MagicMock()
    mock_db.return_value = inst
    f = tmp_path / "x.mp4"; f.write_bytes(b"x")
    deliver_dropbox(str(f), "/Content/ready/x.mp4")
    inst.files_upload.assert_called()
