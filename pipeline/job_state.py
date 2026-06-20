import json
from datetime import datetime, timezone
from pathlib import Path

from filelock import FileLock
from slugify import slugify

from config import ACTIVE_PATH, COST_LEDGER_PATH, JOBS_DIR, PIPELINE

SCHEMA = {
    "job_id": "",
    "airtable_record_id": "",
    "title": "",
    "visual_format": "",
    "status": "ingested",
    "created_at": "",
    "updated_at": "",
    "cost_usd": {
        "elevenlabs": 0.0,
        "heygen": 0.0,
        "runway": 0.0,
        "openai": 0.0,
        "pexels": 0.0,
        "total": 0.0,
    },
    "cost_cap_usd": 15.0,
    "stages": {
        "ingest": "done",
        "voice": "pending",
        "avatar": "pending",
        "broll": "pending",
        "assembly": "pending",
        "export": "pending",
        "delivery": "pending",
    },
    "gates": {
        "gate1": None,
        "gate2": None,
        "gate3": None,
        "gate4": None,
        "gate5": None,
        "gate6": None,
    },
    "heygen_job_id": None,
    "look_avatar_id": "",
    "regeneration_counts": {"voice": 0, "avatar": 0},
    "pexels_clip_ids": [],
    "emphasis_words_cache": {"hash": None, "words": []},
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def make_job_id(title: str) -> str:
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    slug = slugify(title, max_length=60, lowercase=True)
    return f"{date}-{slug}"


class JobState:
    def __init__(self, data: dict):
        self.data = data

    @property
    def folder(self) -> Path:
        return JOBS_DIR / self.data["job_id"]

    @property
    def path(self) -> Path:
        return self.folder / "job.json"

    @classmethod
    def create(cls, record_id: str, title: str, visual_format: str) -> "JobState":
        data = json.loads(json.dumps(SCHEMA))
        data["job_id"] = make_job_id(title)
        data["airtable_record_id"] = record_id
        data["title"] = title
        data["visual_format"] = visual_format
        data["cost_cap_usd"] = PIPELINE["cost_cap_usd"]
        data["created_at"] = data["updated_at"] = _now()
        folder = JOBS_DIR / data["job_id"]
        folder.mkdir(parents=True, exist_ok=True)
        js = cls(data)
        js.save()
        return js

    @classmethod
    def load(cls, job_id: str) -> "JobState":
        path = JOBS_DIR / job_id / "job.json"
        with FileLock(str(path) + ".lock"):
            data = json.loads(path.read_text())
        return cls(data)

    def save(self) -> None:
        self.data["updated_at"] = _now()
        self.folder.mkdir(parents=True, exist_ok=True)
        with FileLock(str(self.path) + ".lock"):
            self.path.write_text(json.dumps(self.data, indent=2))

    def set_stage(self, stage: str, status: str) -> None:
        self.data["stages"][stage] = status

    def set_gate(self, gate: str, decision: str | None) -> None:
        self.data["gates"][gate] = {"decision": decision, "at": _now()}

    def add_cost(self, provider: str, usd: float) -> None:
        self.data["cost_usd"][provider] = round(
            self.data["cost_usd"].get(provider, 0) + usd, 4
        )
        self.data["cost_usd"]["total"] = round(
            sum(v for k, v in self.data["cost_usd"].items() if k != "total"), 4
        )
        CostLedger.append(self.data["job_id"], provider, usd)
        if self.data["cost_usd"]["total"] > self.data["cost_cap_usd"]:
            self.save()
            raise RuntimeError(
                f"cost cap exceeded: ${self.data['cost_usd']['total']:.2f} "
                f"> ${self.data['cost_cap_usd']:.2f}"
            )
        self.save()

    def bump_regen(self, kind: str) -> int:
        self.data["regeneration_counts"][kind] += 1
        self.save()
        return self.data["regeneration_counts"][kind]


class CostLedger:
    @classmethod
    def append(cls, job_id: str, provider: str, usd: float) -> None:
        entries = []
        if COST_LEDGER_PATH.exists():
            entries = json.loads(COST_LEDGER_PATH.read_text())
        entries.append({"at": _now(), "job_id": job_id, "provider": provider, "usd": usd})
        with FileLock(str(COST_LEDGER_PATH) + ".lock"):
            COST_LEDGER_PATH.write_text(json.dumps(entries, indent=2))


class ActiveRegistry:
    @classmethod
    def _read(cls) -> dict:
        if not ACTIVE_PATH.exists():
            return {}
        return json.loads(ACTIVE_PATH.read_text())

    @classmethod
    def _write(cls, data: dict) -> None:
        with FileLock(str(ACTIVE_PATH) + ".lock"):
            ACTIVE_PATH.write_text(json.dumps(data, indent=2))

    @classmethod
    def add(cls, job_id: str, stage: str) -> None:
        d = cls._read()
        d[job_id] = {"stage": stage, "at": _now()}
        cls._write(d)

    @classmethod
    def remove(cls, job_id: str) -> None:
        d = cls._read()
        d.pop(job_id, None)
        cls._write(d)

    @classmethod
    def all(cls) -> dict:
        return cls._read()
