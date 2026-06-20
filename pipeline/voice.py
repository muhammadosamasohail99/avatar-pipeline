import re
from config import Settings, PIPELINE
from modules.elevenlabs_client import text_to_speech
from pipeline.job_state import JobState, ActiveRegistry
from pipeline.notifications import notify_all


def _clean_script(text: str) -> str:
    """Extract spoken content for TTS.

    If the script uses quoted spoken content ("..."), only those segments
    are extracted. Otherwise falls back to stripping known section labels.
    """
    # Normalise smart quotes to straight so matching works uniformly
    text = text.replace('“', '"').replace('”', '"')

    segments = re.findall(r'"(.*?)"', text, re.DOTALL)
    if segments:
        parts = []
        for seg in segments:
            seg = re.sub(r'\[.*?\]', '', seg)   # drop [bracket] instructions
            seg = re.sub(r'  +', ' ', seg).strip()
            if seg:
                parts.append(seg)
        return '\n\n'.join(parts)

    # Fallback for scripts without quoted content: strip section/direction labels
    _LABEL = re.compile(
        r'^(?:HOOK|REHOOK|SLIDE|BODY|CLOSE|CTA|OUTRO|INTRO|OPEN|BRIDGE|BEAT|SETUP|'
        r'SECTION|DATA|EVIDENCE|CHECKLIST|The\s+\w+|Act\s+\d+|Part\s+\d+)\s*[\d\s\(\)]*:\s*',
        re.I
    )
    _DROP = re.compile(
        r'^[A-Z][A-Z0-9\s\-]*:\s*$'  # standalone ALL-CAPS label with no content
        r'|^(?:SCREEN|B[\s\-]?ROLL|VISUAL|SHOT|CAMERA|NOTE|GRAPHIC|TEXT|OVERLAY|'
        r'ANIMATION|CAPTION|TITLE|THUMBNAIL|REVIEW|EDITOR)\b.*',
        re.I
    )
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            lines.append('')
            continue
        if re.match(r'^\[.*\]\s*$', stripped, re.DOTALL):
            continue
        if _DROP.match(stripped):
            continue
        stripped = _LABEL.sub('', stripped)
        stripped = re.sub(r'\[.*?\]', '', stripped).strip()
        if stripped:
            lines.append(stripped)
    return re.sub(r'\n{3,}', '\n\n', '\n'.join(lines)).strip()


def _expand(text: str) -> str:
    for abbr, expansion in PIPELINE["expansions"].items():
        text = re.sub(rf'(?<!\w){re.escape(abbr)}(?!\w)', expansion, text)
    return text


def run_voice(js: JobState) -> None:
    ActiveRegistry.add(js.data["job_id"], "voice")
    try:
        js.set_stage("voice", "running")
        js.save()
        s = Settings()
        script = (js.folder / "script.txt").read_text()
        text = _expand(_clean_script(script))
        out = str(js.folder / "voice.mp3")
        text_to_speech(text, out, s.elevenlabs_voice_id, s.elevenlabs_api_key)
        js.add_cost("elevenlabs", round(len(text) / 1000 * 0.0003, 4))
        js.set_stage("voice", "done")
        js.data["status"] = "gate_1"
        js.save()
        notify_all("", "", "Avatar Pipeline", f"Gate 1 ready: {js.data['title']}")
    except Exception as exc:
        import traceback
        traceback.print_exc()
        js.data["status"] = "error"
        js.data["error"] = str(exc)
        js.data["error_gate"] = ""
        js.save()
    finally:
        ActiveRegistry.remove(js.data["job_id"])
