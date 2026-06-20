import os
import re
import subprocess

import av
import imageio_ffmpeg


def _ffmpeg_exe() -> str:
    return imageio_ffmpeg.get_ffmpeg_exe()


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    if cmd[0] in ("ffmpeg", "ffprobe"):
        cmd = [_ffmpeg_exe()] + cmd[1:]
    return subprocess.run(cmd, check=True, capture_output=True, text=True)


def probe_video(path: str) -> dict:
    with av.open(path) as container:
        v = next((s for s in container.streams if s.type == "video"), None)
        a = next((s for s in container.streams if s.type == "audio"), None)
        dur = float(container.duration) / 1_000_000 if container.duration else 0
        return {
            "duration": dur,
            "width": v.codec_context.width if v else 0,
            "height": v.codec_context.height if v else 0,
            "fps": float(v.average_rate) if v else 0,
            "has_video": v is not None,
            "has_audio": a is not None,
            "size_bytes": os.path.getsize(path),
        }


def get_audio_duration(path: str) -> float:
    with av.open(path) as container:
        if container.duration:
            return float(container.duration) / 1_000_000
        stream = next((s for s in container.streams if s.type == "audio"), None)
        if stream and stream.duration and stream.time_base:
            return float(stream.duration * stream.time_base)
        return 0


def burn_captions(input_path: str, ass_path: str, output_path: str) -> str:
    escaped = ass_path.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
    _run(["ffmpeg", "-y", "-i", input_path,
          "-vf", f"ass='{escaped}'",
          "-c:v", "libx264", "-preset", "medium", "-crf", "18",
          "-c:a", "copy", "-movflags", "+faststart", output_path])
    return output_path


def extract_audio(video_path: str, audio_path: str) -> str:
    _run(["ffmpeg", "-y", "-i", video_path, "-vn", "-acodec", "pcm_s16le",
          "-ar", "16000", "-ac", "1", audio_path])
    return audio_path


def loudnorm(input_path: str, output_path: str, target_lufs: int = -14) -> str:
    _run(["ffmpeg", "-y", "-i", input_path,
          "-af", f"loudnorm=I={target_lufs}:TP=-1.5:LRA=11",
          "-c:v", "libx264", "-preset", "medium", "-crf", "18",
          "-c:a", "aac", "-b:a", "192k", output_path])
    return output_path


def composite_video(avatar_path: str, broll_segments: list[dict], ass_path: str | None,
                    output_path: str) -> str:
    inputs = ["-i", avatar_path]
    for seg in broll_segments:
        inputs += ["-i", seg["clip_path"]]
    filters = []
    last = "[0:v]"
    for i, seg in enumerate(broll_segments, start=1):
        # Scale to fit within 1920x1080, letterbox/pillarbox with black, centred
        filters.append(
            f"[{i}:v]"
            f"scale=1920:1080:force_original_aspect_ratio=decrease,"
            f"pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black,"
            f"setpts=PTS-STARTPTS[b{i}]"
        )
        filters.append(
            f"{last}[b{i}]overlay=enable='between(t,{seg['start']},{seg['end']})'[v{i}]"
        )
        last = f"[v{i}]"
    if ass_path:
        escaped = ass_path.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
        filters.append(f"{last}ass='{escaped}'[vout]")
        last = "[vout]"
    fc = ";".join(filters) if filters else None
    cmd = ["ffmpeg", "-y", *inputs]
    if fc:
        cmd += ["-filter_complex", fc, "-map", last, "-map", "0:a"]
    else:
        cmd += ["-map", "0:v", "-map", "0:a"]
    cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart", output_path]
    _run(cmd)
    return output_path


def reframe_9x16(input_path: str, output_path: str, safe_zone_pct: float = 0.6) -> str:
    info = probe_video(input_path)
    target_w = int(info["height"] * 9 / 16)
    x = max(0, (info["width"] - target_w) // 2)
    _run(["ffmpeg", "-y", "-i", input_path,
          "-vf", f"crop={target_w}:{info['height']}:{x}:0,scale=1080:1920",
          "-c:v", "libx264", "-preset", "medium", "-crf", "18",
          "-c:a", "copy", output_path])
    return output_path
