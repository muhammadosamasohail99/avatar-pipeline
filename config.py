from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).parent
JOBS_DIR = ROOT / "jobs"
ARCHIVE_DIR = ROOT / "archive"
ASSETS_DIR = ROOT / "assets"
LOGS_DIR = ROOT / "logs"
ACTIVE_PATH = ROOT / "active.json"
COST_LEDGER_PATH = ROOT / "cost-ledger.json"


class Settings(BaseSettings):
    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = ""
    heygen_api_key: str = ""
    heygen_avatar_id: str = ""
    heygen_use_v3: bool = True
    heygen_motion_prompt: str = "natural conversational hand gestures, speaking directly to camera"
    pexels_api_key: str = ""
    runway_api_key: str = ""
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash-lite"
    heygen_looks: str = "[]"
    airtable_api_key: str = ""
    airtable_base_id: str = "appiE5ew3MElVDS9g"
    airtable_table_id: str = "tblgfx7nmAMKIL0Km"
    dropbox_token: str = ""
    dropbox_delivery_path: str = "/Content/ready/"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


PIPELINE = {
    "cost_cap_usd": 15.0,
    "concurrency": 2,
    "wpm_target": 160,
    "duration_tolerance": {"gate1": 0.10, "gate2": 0.05, "gate5": 2.0},
    "regen_cap": {"voice": 999, "avatar": 5},
    "lufs_target": -14,
    "max_size_mb": {"16x9": 500, "9x16": 250},
    "poll_interval_sec": 300,
    "heygen_poll_sec": 30,
    "heygen_timeout_sec": 1800,
    "broll_segment_window_sec": (4, 7),
    "relevance_thresholds": {"green": 0.7, "orange": 0.4},
    "expansions": {
        "$1.2M": "1.2 million dollars",
        "3x": "3 times",
        "GPT-4o": "GPT 4 oh",
        "10x": "10 times",
        "AI": "A I",
        "API": "A P I",
    },
    "pronunciations": {
        "Claude": "klawd",
        "Anthropic": "an-throh-pik",
    },
    "caption": {
        "fontname": "Inter",
        "fontsize": 62,
        "fontsize_9x16": 72,
        "primary_colour": "&H00FFFFFF",
        "outline": 0,
        "shadow": 1.5,
        "shadow_colour": "&H66000000",
        "alignment": 2,
        "margin_v_16x9": 108,
        "margin_v_9x16": 148,
        "letter_spacing": -0.5,
        "phrase_min": 3,
        "phrase_max": 5,
        "pause_break_ms": 200,
    },
    "archive_days": 30,
}

def get_heygen_looks() -> list[dict]:
    import json as _json
    try:
        data = _json.loads(Settings().heygen_looks)
        if isinstance(data, list) and len(data) == 1 and isinstance(data[0], list):
            data = data[0]
        if not isinstance(data, list):
            return []
        out = []
        for i, item in enumerate(data):
            if isinstance(item, dict):
                out.append(item)
            elif isinstance(item, str) and item:
                out.append({"label": f"Look {i + 1}", "avatar_id": item})
        return out
    except Exception:
        return []


def ensure_dirs() -> None:
    for d in (JOBS_DIR, ARCHIVE_DIR, LOGS_DIR):
        d.mkdir(parents=True, exist_ok=True)

ensure_dirs()
