import json
import re
from config import PIPELINE
from modules.ass_writer import write_ass, write_srt
from modules.elevenlabs_client import alignment_to_words
from pipeline.job_state import JobState, ActiveRegistry
from pipeline.notifications import notify_all


# ---------------------------------------------------------------------------
# Emphasis analysis — two-pass: rule-based then Gemini with full context
# ---------------------------------------------------------------------------

# Hard blocklist — these are never visually highlighted regardless of Gemini's output.
_FUNCTION_WORDS = frozenset({
    "the", "a", "an",
    "is", "are", "was", "were", "be", "been", "being",
    "to", "of", "in", "on", "at", "by", "for", "with", "from", "into", "about",
    "and", "or", "nor",
    "that", "which", "this", "these", "those",
    "we", "you", "i", "it", "its", "they", "them", "their",
    "he", "she", "our", "your", "my", "his", "her",
    "can", "will", "would", "could", "should", "may", "might",
    "do", "did", "does", "have", "has", "had", "get", "got",
    "just", "also", "very", "so", "as", "if", "then", "than", "when",
    "one", "two", "three", "same", "like", "use", "used",
})


def _bare(word: str) -> str:
    return word.strip(".,!?;:\"'()[]{}–-").lower()


def _rule_emphasis(words: list[dict]) -> set[int]:
    """Always emphasise numbers, percentages, dollar amounts, multipliers, and ranges."""
    pattern = re.compile(
        r'^\$?\d[\d,\.]*(%|x|X)?$'                   # 40%, $547, 2x, 19.8, 300
        r'|^\d+[\d,\.]*[kmb]$'                        # 1.2m, 547b
        r'|^\$?\d[\d,\.]*[–\-]\d[\d,\.]*(%|x|X)?$',  # 8–13%, 73-81%, 2-3x
        re.I
    )
    return {i for i, w in enumerate(words)
            if pattern.match(_bare(w["word"]))}


def _gemini_key_phrases(script: str) -> list[str]:
    """Ask Gemini to return key phrases from the script that should be emphasized.
    Phrase-level output is more reliable than index selection for contextual understanding."""
    from modules.gemini_client import generate
    prompt = (
        "You are styling captions for a social media short-form video.\n\n"
        f"Script:\n{script}\n\n"
        "Identify 6–12 short phrases or single words from this script that a viewer "
        "skimming the captions must notice to understand the core message.\n\n"
        "Think in complete ideas, not isolated words. Good examples:\n"
        "  • Stats with context: '40% of your audience', '2x to 3.5x', '$547 billion'\n"
        "  • Impact claims: 'never sees', 'completely invisible', 'bad results'\n"
        "  • Problem statements: 'optimising on incomplete data', 'wrong buyers'\n"
        "  • Calls to action: 'link in bio', 'run a tracking audit', 'server-side tracking'\n"
        "  • Outcomes: 'nothing changed', 'jumped from', 'reported ROAS'\n\n"
        "Rules:\n"
        "  - Copy the phrase EXACTLY as it appears in the script (same spelling/casing)\n"
        "  - Keep each phrase 1–5 words\n"
        "  - Prefer phrases over lone words where possible\n"
        "  - Do NOT include filler phrases ('and then', 'you know', 'so that')\n\n"
        'Return ONLY a JSON array of strings: ["40% of your audience", "never sees", "link in bio"]'
    )
    text = generate(prompt).strip()
    if "```" in text:
        parts = text.split("```")
        text = parts[1] if len(parts) >= 3 else parts[-1]
        text = re.sub(r"^json\s*", "", text.strip())
    try:
        result = json.loads(text)
        if isinstance(result, list):
            return [str(p) for p in result]
    except Exception:
        pass
    return []


def _match_phrases(key_phrases: list[str], words: list[dict]) -> set[int]:
    """Sliding-window match of key phrases against the word list; return word indices."""
    indices = set()
    bare_words = [_bare(w["word"]) for w in words]
    for phrase in key_phrases:
        # Tokenise the phrase the same way (strip punct, lowercase)
        tokens = [_bare(t) for t in phrase.split() if t.strip()]
        if not tokens:
            continue
        n = len(tokens)
        for start in range(len(bare_words) - n + 1):
            if bare_words[start:start + n] == tokens:
                indices.update(range(start, start + n))
                break  # first occurrence only
    return indices


def assign_emphasis(script: str, words: list[dict]) -> None:
    """Mutate each word dict in-place, setting word['emphasis'] = bool."""
    seed = _rule_emphasis(words)
    try:
        key_phrases = _gemini_key_phrases(script)
        phrase_indices = _match_phrases(key_phrases, words)
    except Exception:
        phrase_indices = set()

    all_emph = phrase_indices | seed
    # Hard-remove function words — articles, prepositions, pronouns, aux verbs
    # that sneak in as part of a matched phrase (e.g. "of" in "40% of your audience")
    all_emph = {i for i in all_emph if _bare(words[i]["word"]) not in _FUNCTION_WORDS}
    all_emph |= seed  # always restore number/stat highlights
    for i, w in enumerate(words):
        w["emphasis"] = i in all_emph


# ---------------------------------------------------------------------------
# Phrase grouping — Gemini decides breaks only; emphasis already on words
# ---------------------------------------------------------------------------

def _group_with_gemini(words: list[dict]) -> list[dict]:
    from modules.gemini_client import generate
    phrase_min = PIPELINE["caption"]["phrase_min"]
    phrase_max = PIPELINE["caption"]["phrase_max"]
    pause_ms = PIPELINE["caption"]["pause_break_ms"]
    word_list = "\n".join(
        f"{i}: {w['word']} ({w['start']:.2f}-{w['end']:.2f})"
        for i, w in enumerate(words)
    )
    prompt = (
        f"Group these video caption words into on-screen phrases.\n"
        f"Rules:\n"
        f"  - Each phrase must have {phrase_min}–{phrase_max} words\n"
        f"  - Break at natural pauses (gaps ≥{pause_ms}ms) and sentence boundaries\n\n"
        f"Words:\n{word_list}\n\n"
        f"Respond with ONLY valid JSON — an array of index arrays:\n"
        f"[[0,1,2],[3,4,5,6], ...]\n"
        f"Cover every index from 0 to {len(words)-1}."
    )
    text = generate(prompt).strip()
    if "```" in text:
        parts = text.split("```")
        text = parts[1] if len(parts) >= 3 else parts[-1]
        text = re.sub(r"^json\s*", "", text.strip())
    groups = json.loads(text)
    phrases = []
    for group in groups:
        idx = [i for i in group if 0 <= i < len(words)]
        if not idx:
            continue
        pw = [words[i] for i in idx]
        phrases.append({
            "start": pw[0]["start"],
            "end": pw[-1]["end"],
            "words": [{"word": w["word"], "emphasis": w.get("emphasis", False)} for w in pw],
        })
    return phrases


def _group_algorithmic(words: list[dict]) -> list[dict]:
    phrase_min = PIPELINE["caption"]["phrase_min"]
    phrase_max = PIPELINE["caption"]["phrase_max"]
    pause_ms = PIPELINE["caption"]["pause_break_ms"]
    phrases: list[dict] = []
    current: list[dict] = []
    for i, w in enumerate(words):
        current.append(w)
        at_max = len(current) >= phrase_max
        at_min = len(current) >= phrase_min
        is_last = i == len(words) - 1
        has_pause = (not is_last and
                     (words[i + 1]["start"] - w["end"]) * 1000 >= pause_ms)
        if at_max or (at_min and has_pause) or (at_min and is_last):
            phrases.append({
                "start": current[0]["start"],
                "end": current[-1]["end"],
                "words": [{"word": ww["word"], "emphasis": ww.get("emphasis", False)}
                          for ww in current],
            })
            current = []
    if current:
        if phrases:
            phrases[-1]["words"] += [{"word": ww["word"], "emphasis": ww.get("emphasis", False)}
                                      for ww in current]
            phrases[-1]["end"] = current[-1]["end"]
        else:
            phrases.append({
                "start": current[0]["start"],
                "end": current[-1]["end"],
                "words": [{"word": ww["word"], "emphasis": ww.get("emphasis", False)}
                          for ww in current],
            })
    return phrases


def build_phrases(words: list[dict]) -> list[dict]:
    try:
        return _group_with_gemini(words)
    except Exception:
        return _group_algorithmic(words)


# ---------------------------------------------------------------------------
# Caption preview helper
# ---------------------------------------------------------------------------

def render_preview(avatar_path: str, ass_path: str, output_path: str) -> str:
    from modules.ffmpeg_utils import composite_video
    composite_video(avatar_path, [], ass_path, output_path)
    return output_path


# ---------------------------------------------------------------------------
# Pipeline stage
# ---------------------------------------------------------------------------

async def run_captions(js: JobState) -> None:
    ActiveRegistry.add(js.data["job_id"], "captions")
    try:
        js.save()
        align_path = js.folder / "voice_alignment.json"
        if not align_path.exists():
            raise FileNotFoundError("voice_alignment.json missing — run voice stage first")
        alignment = json.loads(align_path.read_text())
        words = alignment_to_words(alignment)

        # Pass 1: assign emphasis across all words using full script context
        script = (js.folder / "script.txt").read_text() if (js.folder / "script.txt").exists() else ""
        assign_emphasis(script, words)

        # Pass 2: group into caption phrases (emphasis flags already set on each word)
        phrases = build_phrases(words)
        (js.folder / "phrases.json").write_text(json.dumps(phrases, indent=2))

        # Write ASS files for both formats
        write_ass(str(js.folder / "captions.ass"), phrases,
                  margin_v=PIPELINE["caption"]["margin_v_16x9"],
                  play_res_x=1920, play_res_y=1080,
                  fontsize=PIPELINE["caption"]["fontsize"])
        write_ass(str(js.folder / "captions_9x16.ass"), phrases,
                  margin_v=PIPELINE["caption"]["margin_v_9x16"],
                  play_res_x=1080, play_res_y=1920,
                  fontsize=PIPELINE["caption"]["fontsize_9x16"])
        write_srt(str(js.folder / "captions.srt"), phrases)

        avatar_path = js.folder / "avatar.mp4"
        if avatar_path.exists():
            render_preview(str(avatar_path), str(js.folder / "captions.ass"),
                           str(js.folder / "preview_captions.mp4"))
        js.data["status"] = "gate_4"
        js.save()
        notify_all("", "", "Avatar Pipeline", f"Gate 4 ready: {js.data['title']}")
    except Exception as exc:
        import traceback
        traceback.print_exc()
        js.data["status"] = "error"
        js.data["error"] = str(exc)
        js.data["error_gate"] = "3"
        js.save()
    finally:
        ActiveRegistry.remove(js.data["job_id"])
