import os
import dropbox
import dropbox.files
from pathlib import Path
from slugify import slugify
from config import Settings, PIPELINE
from modules.ffmpeg_utils import loudnorm, reframe_9x16, burn_captions, probe_video
from pipeline.job_state import JobState, ActiveRegistry

_CHUNK = 50 * 1024 * 1024   # 50 MB per chunk
_SMALL = 150 * 1024 * 1024  # files under 150 MB use single-shot upload


def slug_filename(title: str, fmt: str, date: str) -> str:
    s = slugify(title, max_length=60, lowercase=True)
    return f"{date}-{s}-{fmt}.mp4"


def deliver_dropbox(local_path: str, remote_path: str) -> None:
    s = Settings()
    # timeout=600 prevents write-timeout on large files; 10 min per chunk is generous
    dbx = dropbox.Dropbox(s.dropbox_token, timeout=600)
    file_size = os.path.getsize(local_path)
    mode = dropbox.files.WriteMode("overwrite")

    try:
        with open(local_path, "rb") as f:
            if file_size <= _SMALL:
                dbx.files_upload(f.read(), remote_path, mode=mode)
            else:
                # Chunked upload session for large files
                session = dbx.files_upload_session_start(f.read(_CHUNK))
                cursor = dropbox.files.UploadSessionCursor(
                    session_id=session.session_id, offset=f.tell()
                )
                commit = dropbox.files.CommitInfo(path=remote_path, mode=mode)
                while True:
                    remaining = file_size - f.tell()
                    if remaining <= _CHUNK:
                        dbx.files_upload_session_finish(f.read(remaining), cursor, commit)
                        break
                    else:
                        dbx.files_upload_session_append_v2(f.read(_CHUNK), cursor)
                        cursor = dropbox.files.UploadSessionCursor(
                            session_id=session.session_id, offset=f.tell()
                        )
    except dropbox.exceptions.AuthError:
        raise RuntimeError(
            "Dropbox token expired. Go to dropbox.com/developers/apps → "
            "your app → Settings → Generate access token, "
            "then update DROPBOX_TOKEN in your .env file and restart the server."
        )


def export_prechecks(js: JobState) -> list[dict]:
    out = []
    for fmt in ("16x9", "9x16"):
        p = js.folder / f"final_{fmt}.mp4"
        if not p.exists():
            out.append({"id": fmt, "status": "warn", "message": f"{fmt} missing"})
            continue
        try:
            info = probe_video(str(p))
            size_mb = info.get("size_bytes", 0) / 1024 / 1024
        except Exception:
            size_mb = 0
        cap = PIPELINE["max_size_mb"][fmt]
        status = "pass" if size_mb <= cap else "warn"
        out.append({"id": fmt, "status": status,
                    "message": f"{fmt}: {size_mb:.1f}MB (cap {cap}MB)"})
    return out


async def run_export(js: JobState) -> None:
    ActiveRegistry.add(js.data["job_id"], "export")
    try:
        js.set_stage("export", "running"); js.save()

        # Prefer no-captions composite so each format gets its own caption burn.
        # Fall back to composite.mp4 for jobs assembled before this change.
        nocaps = js.folder / "composite_nocaps.mp4"
        comp = js.folder / "composite.mp4"
        source = str(nocaps) if nocaps.exists() else str(comp)

        # Step 1: loudnorm (audio only, video passthrough) → normalised base
        master_nocaps = js.folder / "master_nocaps.mp4"
        loudnorm(source, str(master_nocaps), target_lufs=PIPELINE["lufs_target"])

        # Step 2: 16:9 — burn 16:9 captions onto normalised base
        ass_16x9 = js.folder / "captions.ass"
        final_16x9 = js.folder / "final_16x9.mp4"
        if ass_16x9.exists():
            burn_captions(str(master_nocaps), str(ass_16x9), str(final_16x9))
        else:
            master_nocaps.rename(final_16x9)

        # Step 3: 9:16 — crop first (no captions yet), then burn 9:16 captions
        nine_raw = js.folder / "nine_raw.mp4"
        try:
            reframe_9x16(str(master_nocaps), str(nine_raw))
        except Exception:
            (js.folder / "9x16_warning.txt").write_text("reframe failed; skipped")
            nine_raw = None

        if nine_raw and nine_raw.exists():
            ass_9x16 = js.folder / "captions_9x16.ass"
            final_9x16 = js.folder / "final_9x16.mp4"
            if ass_9x16.exists():
                burn_captions(str(nine_raw), str(ass_9x16), str(final_9x16))
            else:
                nine_raw.rename(final_9x16)
            # clean up temp
            if nine_raw.exists():
                nine_raw.unlink()

        # clean up normalised base (captions copies are the keepers)
        if master_nocaps.exists() and final_16x9.exists():
            master_nocaps.unlink()

        js.set_stage("export", "done")
        js.data["status"] = "gate_6"; js.save()
    except Exception as exc:
        import traceback
        traceback.print_exc()
        js.data["status"] = "error"
        js.data["error"] = str(exc)
        js.data["error_gate"] = "5"
        js.save()
    finally:
        ActiveRegistry.remove(js.data["job_id"])


async def run_delivery(js: JobState) -> None:
    ActiveRegistry.add(js.data["job_id"], "delivery")
    try:
        js.set_stage("delivery", "running"); js.save()
        s = Settings()
        date = js.data["created_at"][:10]
        delivered: list[str] = []
        skipped: list[str] = []

        for fmt in ("16x9", "9x16"):
            local = js.folder / f"final_{fmt}.mp4"
            if not local.exists():
                skipped.append(fmt)
                print(f"[delivery] WARNING: final_{fmt}.mp4 not found — skipping")
                continue
            remote = s.dropbox_delivery_path + slug_filename(js.data["title"], fmt, date)
            js.data["delivery_note"] = f"Uploading {fmt}…"; js.save()
            deliver_dropbox(str(local), remote)
            delivered.append(fmt)

        srt = js.folder / "captions.srt"
        if srt.exists():
            remote_srt = (s.dropbox_delivery_path
                          + slug_filename(js.data["title"], "captions", date).replace(".mp4", ".srt"))
            js.data["delivery_note"] = "Uploading captions…"; js.save()
            deliver_dropbox(str(srt), remote_srt)
            delivered.append("captions")

        if skipped:
            print(f"[delivery] Skipped formats (file missing): {skipped}")

        from pipeline import ingest as ingest_mod
        ingest_mod.mark_status(js.data["airtable_record_id"], "Published")
        js.set_stage("delivery", "done")
        js.data["status"] = "delivered"
        js.data["delivered_formats"] = delivered
        js.data["skipped_formats"] = skipped
        js.data.pop("delivery_note", None)
        js.save()
        from pipeline.notifications import notify_all
        notify_all(js.data["airtable_record_id"], "Published",
                   "Avatar Pipeline", f"Delivered: {js.data['title']}")
    except Exception as exc:
        import traceback
        traceback.print_exc()
        js.data["status"] = "error"
        js.data["error"] = str(exc)
        js.data["error_gate"] = "6"
        js.save()
    finally:
        ActiveRegistry.remove(js.data["job_id"])
