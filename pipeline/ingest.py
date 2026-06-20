from pyairtable import Table
from config import Settings, JOBS_DIR, PIPELINE
from pipeline.job_state import JobState, ActiveRegistry

def _table() -> Table:
    s = Settings()
    return Table(s.airtable_api_key, s.airtable_base_id, s.airtable_table_id)

def poll_once() -> list[JobState]:
    t = _table()
    records = t.all(formula="{Pipeline Status}='Filming'")
    created: list[JobState] = []
    for rec in records:
        f = rec["fields"]
        vf = f.get("Visual Format", "Selfie")
        script = f.get("Script", "").strip()
        if not script:
            print(f"[ingest] skipping {rec['id']} — Script field is empty")
            continue
        t.update(rec["id"], {"Pipeline Status": "Filmed"})
        js = JobState.create(rec["id"], f.get("Title", "untitled"), vf)
        (js.folder / "script.txt").write_text(script)
        (js.folder / "hook.txt").write_text(f.get("Hook 1", ""))
        created.append(js)
    return created

def detect_orphans() -> list[tuple[str, str]]:
    t = _table()
    records = t.all(formula="{Pipeline Status}='Processing'")
    active = set(ActiveRegistry.all().keys())
    orphans: list[tuple[str, str]] = []
    for rec in records:
        title = rec["fields"].get("Title", "")
        found = any(p.exists() for p in JOBS_DIR.glob(f"*-{title.lower().replace(' ', '-')}*/job.json"))
        if not found and rec["id"] not in {a for a in active}:
            orphans.append((rec["id"], title))
    return orphans

def mark_status(record_id: str, status: str) -> None:
    _table().update(record_id, {"Pipeline Status": status})
