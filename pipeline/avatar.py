import asyncio
import httpx
from config import Settings, PIPELINE
from pipeline.job_state import JobState, ActiveRegistry
from pipeline.notifications import notify_all

HEYGEN_BASE = "https://api.heygen.com"


async def _upload_audio(path: str, api_key: str) -> str:
    """Upload audio to HeyGen v3 assets. Returns asset_id."""
    async with httpx.AsyncClient(timeout=120) as c:
        with open(path, "rb") as f:
            r = await c.post(
                f"{HEYGEN_BASE}/v3/assets",
                headers={"X-Api-Key": api_key},
                files={"file": ("voice.mp3", f, "audio/mpeg")},
            )
        if not r.is_success:
            raise RuntimeError(f"HeyGen upload {r.status_code}: {r.text}")
        data = r.json()
        if data.get("error"):
            raise RuntimeError(f"HeyGen asset upload error: {data['error']}")
        return data["data"]["asset_id"]


# ---------------------------------------------------------------------------
# v3 — Avatar V with gesture support
# ---------------------------------------------------------------------------

async def _submit_v3(avatar_id: str, asset_id: str, api_key: str, motion_prompt: str) -> str:
    """Submit via HeyGen v3 API (Avatar V + motion_prompt). Returns video_id."""
    payload: dict = {
        "type": "avatar",
        "avatar_id": avatar_id,
        "audio_asset_id": asset_id,
        "engine": {"type": "avatar_v"},
        "aspect_ratio": "16:9",
        "resolution": "1080p",
        "output_format": "mp4",
    }
    if motion_prompt:
        payload["motion_prompt"] = motion_prompt

    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post(
            f"{HEYGEN_BASE}/v3/videos",
            headers={"X-Api-Key": api_key, "Content-Type": "application/json"},
            json=payload,
        )
        if not r.is_success:
            raise RuntimeError(f"HeyGen v3 submit {r.status_code}: {r.text}")
        resp = r.json()
        if resp.get("error"):
            raise RuntimeError(f"HeyGen v3 error: {resp['error']}")
        # v3 returns video_id at top level; guard against wrapped shape too
        video_id = resp.get("video_id") or (resp.get("data") or {}).get("video_id")
        if not video_id:
            raise RuntimeError(f"HeyGen v3: no video_id in response: {resp}")
        return video_id


async def _poll_v3(video_id: str, api_key: str) -> str:
    """Poll v3 status endpoint until completed. Returns download URL."""
    interval = PIPELINE["heygen_poll_sec"]
    timeout = PIPELINE["heygen_timeout_sec"]
    elapsed = 0
    async with httpx.AsyncClient(timeout=30) as c:
        while elapsed < timeout:
            await asyncio.sleep(interval)
            elapsed += interval
            r = await c.get(
                f"{HEYGEN_BASE}/v3/videos/{video_id}",
                headers={"X-Api-Key": api_key},
            )
            if not r.is_success:
                raise RuntimeError(f"HeyGen v3 poll {r.status_code}: {r.text}")
            d = r.json()
            if "data" in d:
                d = d["data"]
            status = d.get("status", "")
            if status == "completed":
                return d["video_url"]
            if status in ("failed", "error"):
                msg = d.get("failure_message") or d.get("error", "")
                raise RuntimeError(f"HeyGen v3 failed: {msg}")
    raise TimeoutError(f"HeyGen v3 timed out after {timeout}s")


# ---------------------------------------------------------------------------
# v2 — Avatar IV (kept as fallback; set HEYGEN_USE_V3=false to use)
# ---------------------------------------------------------------------------

async def _submit_v2(avatar_id: str, asset_id: str, api_key: str) -> str:
    """Submit via HeyGen v2 API. Returns video_id."""
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post(
            f"{HEYGEN_BASE}/v2/video/generate",
            headers={"X-Api-Key": api_key, "Content-Type": "application/json"},
            json={
                "video_inputs": [{
                    "character": {
                        "type": "avatar",
                        "avatar_id": avatar_id,
                    },
                    "voice": {"type": "audio", "audio_asset_id": asset_id},
                    "background": {"type": "color", "value": "#ffffff"},
                }],
                "dimension": {"width": 1920, "height": 1080},
            },
        )
        if not r.is_success:
            raise RuntimeError(f"HeyGen v2 submit {r.status_code}: {r.text}")
        data = r.json()
        if data.get("error"):
            raise RuntimeError(f"HeyGen v2 error: {data['error']}")
        return data["data"]["video_id"]


async def _poll_v2(video_id: str, api_key: str) -> str:
    """Poll v1 status endpoint (for v2-submitted jobs). Returns download URL."""
    interval = PIPELINE["heygen_poll_sec"]
    timeout = PIPELINE["heygen_timeout_sec"]
    elapsed = 0
    async with httpx.AsyncClient(timeout=30) as c:
        while elapsed < timeout:
            await asyncio.sleep(interval)
            elapsed += interval
            r = await c.get(
                f"{HEYGEN_BASE}/v1/video_status.get",
                params={"video_id": video_id},
                headers={"X-Api-Key": api_key},
            )
            if not r.is_success:
                raise RuntimeError(f"HeyGen poll {r.status_code}: {r.text}")
            d = r.json()["data"]
            if d["status"] == "completed":
                return d["video_url"]
            if d["status"] in ("failed", "error"):
                raise RuntimeError(f"HeyGen failed: {d.get('error', '')}")
    raise TimeoutError(f"HeyGen timed out after {timeout}s")


async def _download(url: str, dest: str) -> None:
    async with httpx.AsyncClient(timeout=600) as c:
        async with c.stream("GET", url) as r:
            r.raise_for_status()
            with open(dest, "wb") as f:
                async for chunk in r.aiter_bytes(8192):
                    f.write(chunk)


async def resume_avatar_poll(js: JobState) -> None:
    """Resume polling for a job that already has a heygen_job_id (server restart recovery)."""
    ActiveRegistry.add(js.data["job_id"], "avatar")
    try:
        s = Settings()
        video_id = js.data["heygen_job_id"]
        api_version = js.data.get("heygen_api_version", "v2")
        if api_version == "v3":
            video_url = await _poll_v3(video_id, s.heygen_api_key)
        else:
            video_url = await _poll_v2(video_id, s.heygen_api_key)
        await _download(video_url, str(js.folder / "avatar.mp4"))
        js.set_stage("avatar", "done")
        js.data["status"] = "gate_2"
        js.save()
        notify_all("", "", "Avatar Pipeline", f"Gate 2 ready: {js.data['title']}")
    except Exception as exc:
        import traceback
        traceback.print_exc()
        js.data["status"] = "error"
        js.data["error"] = str(exc)
        js.data["error_gate"] = "1"
        js.save()
    finally:
        ActiveRegistry.remove(js.data["job_id"])


async def run_avatar(js: JobState) -> None:
    ActiveRegistry.add(js.data["job_id"], "avatar")
    try:
        js.set_stage("avatar", "running")
        js.save()
        s = Settings()
        avatar_id = js.data.get("look_avatar_id") or s.heygen_avatar_id
        asset_id = await _upload_audio(str(js.folder / "voice.mp3"), s.heygen_api_key)

        if s.heygen_use_v3:
            video_id = await _submit_v3(avatar_id, asset_id, s.heygen_api_key, s.heygen_motion_prompt)
            js.data["heygen_api_version"] = "v3"
        else:
            video_id = await _submit_v2(avatar_id, asset_id, s.heygen_api_key)
            js.data["heygen_api_version"] = "v2"

        js.data["heygen_job_id"] = video_id
        js.save()

        if s.heygen_use_v3:
            video_url = await _poll_v3(video_id, s.heygen_api_key)
        else:
            video_url = await _poll_v2(video_id, s.heygen_api_key)

        await _download(video_url, str(js.folder / "avatar.mp4"))
        js.set_stage("avatar", "done")
        js.data["status"] = "gate_2"
        js.save()
        notify_all("", "", "Avatar Pipeline", f"Gate 2 ready: {js.data['title']}")
    except Exception as exc:
        import traceback
        traceback.print_exc()
        js.data["status"] = "error"
        js.data["error"] = str(exc)
        js.data["error_gate"] = "1"
        js.save()
    finally:
        ActiveRegistry.remove(js.data["job_id"])
