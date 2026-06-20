from modules.ass_writer import format_ass_time, write_ass, write_srt


def test_format_ass_time():
    assert format_ass_time(0) == "0:00:00.00"
    assert format_ass_time(65.5) == "0:01:05.50"
    assert format_ass_time(3661.234) == "1:01:01.23"


def test_write_ass(tmp_path):
    phrases = [
        {"start": 0.0, "end": 1.5, "words": [
            {"word": "Never", "emphasis": True},
            {"word": "do", "emphasis": False},
            {"word": "this", "emphasis": False},
        ]},
        {"start": 1.6, "end": 3.0, "words": [
            {"word": "always", "emphasis": True},
            {"word": "win", "emphasis": False},
        ]},
    ]
    out = tmp_path / "c.ass"
    write_ass(str(out), phrases, margin_v=108)
    content = out.read_text()
    assert "[Script Info]" in content
    assert "Style: Default,Inter,62" in content
    assert "{\\i1\\blur3}Never{\\i0\\blur0\\shad1.5}" in content
    assert "0:00:00.00,0:00:01.50" in content


def test_write_srt(tmp_path):
    phrases = [{"start": 0.0, "end": 1.5, "words": [
        {"word": "hello", "emphasis": False}, {"word": "world", "emphasis": False}
    ]}]
    out = tmp_path / "c.srt"
    write_srt(str(out), phrases)
    text = out.read_text()
    assert "1\n00:00:00,000 --> 00:00:01,500\nhello world" in text
