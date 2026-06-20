from modules.elevenlabs_client import alignment_to_words

def test_alignment_to_words_basic():
    alignment = {
        "characters": ["h", "i", " ", "y", "o", "u"],
        "character_start_times_seconds": [0.0, 0.1, 0.2, 0.3, 0.4, 0.5],
        "character_end_times_seconds": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6],
    }
    words = alignment_to_words(alignment)
    assert words == [
        {"word": "hi", "start": 0.0, "end": 0.2},
        {"word": "you", "start": 0.3, "end": 0.6},
    ]
