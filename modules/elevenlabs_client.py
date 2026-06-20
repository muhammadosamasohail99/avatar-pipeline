import base64
import json
import requests


def text_to_speech(text: str, output_path: str, voice_id: str, api_key: str) -> str:
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/with-timestamps"
    headers = {"xi-api-key": api_key, "Content-Type": "application/json"}
    payload = {
        "text": text,
        "model_id": "eleven_turbo_v2_5",
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.8, "style": 0.2, "use_speaker_boost": True},
    }
    response = requests.post(url, headers=headers, json=payload, timeout=120)
    response.raise_for_status()
    data = response.json()
    audio_bytes = base64.b64decode(data["audio_base64"])
    with open(output_path, "wb") as f:
        f.write(audio_bytes)
    alignment_path = output_path.replace(".mp3", "_alignment.json")
    if data.get("alignment"):
        with open(alignment_path, "w") as f:
            json.dump(data["alignment"], f)
    return output_path


def alignment_to_words(alignment: dict) -> list[dict]:
    chars = alignment["characters"]
    starts = alignment["character_start_times_seconds"]
    ends = alignment["character_end_times_seconds"]
    words: list[dict] = []
    current_word: list[str] = []
    word_start = None
    last_char_end = None
    for ch, cs, ce in zip(chars, starts, ends):
        if ch == " ":
            if current_word:
                words.append({"word": "".join(current_word), "start": word_start, "end": last_char_end})
                current_word, word_start = [], None
        else:
            if word_start is None:
                word_start = cs
            current_word.append(ch)
            last_char_end = ce
    if current_word:
        words.append({"word": "".join(current_word), "start": word_start, "end": last_char_end or word_start})
    return words
