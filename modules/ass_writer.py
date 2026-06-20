from pathlib import Path

ASS_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: {play_res_x}
PlayResY: {play_res_y}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Inter,{fontsize},&H00FFFFFF,&H000000FF,&H00000000,&H66000000,1,0,0,0,100,100,-0.5,0,1,0,1.5,2,40,40,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def format_ass_time(t: float) -> str:
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def _format_srt_time(t: float) -> str:
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = int(t % 60)
    ms = int((t - int(t)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _render_word(word: str, emphasis: bool) -> str:
    if emphasis:
        # ASS colour format is &HAABBGGRR — #F0C040 (golden yellow) = &H0040C0F0
        return "{\\c&H0040C0F0&\\u1}" + word + "{\\c&H00FFFFFF&\\u0}"
    return word


def write_ass(path: str, phrases: list[dict], margin_v: int = 108,
              play_res_x: int = 1920, play_res_y: int = 1080,
              fontsize: int = 62) -> str:
    header = ASS_HEADER.format(margin_v=margin_v, play_res_x=play_res_x,
                               play_res_y=play_res_y, fontsize=fontsize)
    lines = [header]
    for ph in phrases:
        start = format_ass_time(ph["start"])
        end = format_ass_time(ph["end"])
        text = " ".join(_render_word(w["word"], w.get("emphasis", False)) for w in ph["words"])
        lines.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}")
    Path(path).write_text("\n".join(lines))
    return path


def write_srt(path: str, phrases: list[dict]) -> str:
    out = []
    for i, ph in enumerate(phrases, start=1):
        text = " ".join(w["word"] for w in ph["words"])
        out.append(f"{i}\n{_format_srt_time(ph['start'])} --> {_format_srt_time(ph['end'])}\n{text}\n")
    Path(path).write_text("\n".join(out))
    return path
