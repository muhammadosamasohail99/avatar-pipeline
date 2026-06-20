import subprocess
from pipeline import ingest as ingest_mod

def notify_macos(title: str, body: str) -> None:
    script = f'display notification "{body}" with title "{title}"'
    try:
        subprocess.run(["osascript", "-e", script], check=False, timeout=5)
    except Exception:
        pass

async def push_in_app(message_html: str) -> None:
    from main import notify
    await notify(message_html)

def notify_all(record_id: str, airtable_status: str, title: str, body: str) -> None:
    if record_id and airtable_status:
        try:
            ingest_mod.mark_status(record_id, airtable_status)
        except Exception:
            pass
    notify_macos(title, body)
