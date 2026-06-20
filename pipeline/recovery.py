import json
import shutil
from datetime import datetime, timezone, timedelta
from config import JOBS_DIR, ARCHIVE_DIR, ACTIVE_PATH
from pipeline.job_state import JobState, ActiveRegistry

STAGE_ORDER = ["voice", "avatar", "broll", "captions", "assembly", "export", "delivery"]
STAGE_TO_GATE = {"voice": "gate_1", "avatar": "gate_2", "broll": "gate_3",
                 "captions": "gate_4", "assembly": "gate_5", "export": "gate_6",
                 "delivery": "delivered"}

def next_resume_status(data: dict) -> str:
    for stage in STAGE_ORDER:
        if data["stages"].get(stage) != "done":
            prev_idx = STAGE_ORDER.index(stage) - 1
            if prev_idx < 0:
                return "ingested"
            prev = STAGE_ORDER[prev_idx]
            return STAGE_TO_GATE.get(prev, "ingested")
    return "delivered"

def resume_orphans() -> list[dict]:
    active = ActiveRegistry.all()
    resumed = []
    for job_id in list(active.keys()):
        try:
            js = JobState.load(job_id)
        except FileNotFoundError:
            ActiveRegistry.remove(job_id)
            continue
        target = next_resume_status(js.data)
        js.data["status"] = target
        js.save()
        ActiveRegistry.remove(job_id)
        resumed.append({"job_id": job_id, "status": target})
    return resumed

def archive_old(days: int = 30) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    moved = 0
    for p in JOBS_DIR.glob("*/job.json"):
        try:
            data = json.loads(p.read_text())
        except Exception:
            continue
        if data.get("status") not in ("delivered", "paused_edit"):
            continue
        created = datetime.fromisoformat(data["created_at"])
        if created < cutoff:
            dest = ARCHIVE_DIR / p.parent.name
            shutil.move(str(p.parent), str(dest))
            moved += 1
    return moved
