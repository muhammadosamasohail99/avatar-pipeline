<div align="center">

# Avatar Pipeline

**End-to-end AI video production — script to delivered file, zero manual editing.**

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![FFmpeg](https://img.shields.io/badge/FFmpeg-required-007808?style=flat-square&logo=ffmpeg&logoColor=white)](https://ffmpeg.org)
[![License](https://img.shields.io/badge/License-Private-red?style=flat-square)](#license)

</div>

---

Takes a script from Airtable. Synthesizes voice, generates an AI avatar, sources B-roll, burns in captions, assembles and exports dual-format video, then delivers to Dropbox — with a human-in-the-loop review gate at every major stage.

Built with FastAPI, HTMX, ElevenLabs, HeyGen, Pexels, Google Gemini, and FFmpeg. No frontend build tooling. No bundler. Plain HTML served by FastAPI.

---

## Pipeline

```
Airtable  ──►  Voice (ElevenLabs)
                    └── Gate 1: Audio review
               Avatar (HeyGen v3)
                    └── Gate 2: Avatar review
               B-roll (Pexels + Runway)
                    └── Gate 3: B-roll selection
               Captions (WhisperX + Gemini)
                    └── Gate 4: Caption editor
               Assembly (FFmpeg filter_complex)
                    └── Gate 5: Composite review
               Export (16:9 + 9:16 reframe)
                    └── Gate 6: Final review
               Delivery (Dropbox)
```

Every stage runs async. The app polls Airtable every 5 minutes, processes up to 2 jobs concurrently, and recovers in-progress jobs automatically on restart. You review and approve at each gate through a local web UI at `http://localhost:8000`.

---

## Features

| | |
|---|---|
| **End-to-end automation** | Raw script → delivered video with no manual editing |
| **6 review gates** | Approve, regenerate, or edit at every stage before advancing |
| **Dual format export** | 16:9 master + 9:16 center-crop reframe, generated automatically |
| **Smart captions** | Phrase-chunked subtitles with Gemini-powered emphasis highlighting |
| **Multi-source B-roll** | Pexels stock footage, Runway AI-generated clips, or screen recordings |
| **Format routing** | Selfie, Screen Recording, and Split Screen layouts handled automatically |
| **Live dashboard** | SSE-powered job updates, per-job cost tracking, macOS notifications |
| **Resilient** | Orphan job recovery on startup, 30-day automatic archive rotation |
| **Zero build tooling** | Plain HTML + HTMX — no npm, no bundler |

---

## Tech Stack

| Layer | Technology |
|---|---|
| API server | FastAPI + Uvicorn |
| Frontend | HTML, HTMX, Server-Sent Events |
| Voice synthesis | ElevenLabs |
| Avatar video | HeyGen v3 |
| B-roll — stock | Pexels |
| B-roll — AI generated | Runway ML |
| Caption emphasis | Google Gemini 2.5 Flash |
| Video processing | FFmpeg + WhisperX |
| Job storage | Airtable |
| Delivery | Dropbox |

---

## Prerequisites

**System dependencies**

```bash
# macOS
brew install ffmpeg

# Ubuntu / Debian
sudo apt install ffmpeg

# WhisperX (caption transcription)
pip install whisperx

# Inter font — place .ttf files in assets/fonts/
# Download: https://rsms.me/inter/
```

**API keys required**

| Service | Purpose |
|---|---|
| Airtable | Script source + status updates |
| ElevenLabs | Voice synthesis |
| HeyGen | AI avatar video generation |
| Pexels | Stock B-roll footage |
| Runway ML | AI-generated B-roll |
| Google Gemini | Caption emphasis scoring |
| Dropbox | Delivery destination |

---

## Quickstart

```bash
git clone https://github.com/muhammadosamasohail99/avatar-pipeline.git
cd avatar-pipeline

python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate

pip install -r requirements.txt
```

Copy `.env.example` to `.env` and fill in your keys:

```bash
cp .env.example .env
```

```env
AIRTABLE_API_KEY=
AIRTABLE_BASE_ID=
AIRTABLE_TABLE_ID=

ELEVENLABS_API_KEY=
ELEVENLABS_VOICE_ID=

HEYGEN_API_KEY=
HEYGEN_AVATAR_ID=

PEXELS_API_KEY=
RUNWAY_API_KEY=

GEMINI_API_KEY=
GEMINI_MODEL=gemini-2.5-flash-lite

DROPBOX_TOKEN=
DROPBOX_DELIVERY_PATH=/Content/ready/
```

Start the server:

```bash
uvicorn main:app --reload --port 8000
```

Open `http://localhost:8000`.

---

## Review Gates

Each gate lives at `/jobs/{job_id}/gate{N}`.

| Gate | Reviews | Actions |
|---|---|---|
| **1 — Audio** | Waveform, duration, silence check | Approve → avatar, Regenerate, Edit script |
| **2 — Avatar** | Frame integrity, quality checks | Approve → B-roll, Regenerate (max 5×) |
| **3 — B-roll** | Per-segment clip grid | Pick, Skip, Refresh, Upload screen recording |
| **4 — Captions** | Per-word emphasis toggle, re-render preview | Re-render, Approve → assembly |
| **5 — Composite** | Full video with flag-timestamp tool | Flag issues, Async re-render, Approve → export |
| **6 — Export** | 16:9 + 9:16 side-by-side, synchronized scrub | Deliver to Dropbox |

**Seed a test job** (no Airtable required):

```bash
python make_test_job.py
# → job_id: 2026-05-16-my-test-video

# Navigate directly to any gate:
open http://localhost:8000/jobs/2026-05-16-my-test-video/gate1
```

---

## Airtable Schema

| Field | Type | Notes |
|---|---|---|
| `Title` | Single line text | Used as the job slug |
| `Script` | Long text | Full video script |
| `Pipeline Status` | Single select | `Processing` · `Filming` · `Ready to Post` · `Needs Edit` |
| `Visual Format` | Single select | `Selfie` · `Screen Recording` · `Split Screen` |

---

## Project Structure

```
avatar-pipeline/
├── main.py               # FastAPI app, routes, SSE live updates
├── config.py             # Settings, pipeline constants
├── requirements.txt
│
├── pipeline/
│   ├── ingest.py         # Airtable polling, job creation, status locking
│   ├── job_state.py      # JobState, CostLedger, ActiveRegistry
│   ├── voice.py          # ElevenLabs voice synthesis
│   ├── avatar.py         # HeyGen v3 avatar generation
│   ├── broll.py          # Pexels + Runway sourcing, relevance scoring
│   ├── captions.py       # WhisperX transcription + Gemini emphasis
│   ├── assembly.py       # FFmpeg filter_complex (B-roll + caption burn-in)
│   ├── export.py         # loudnorm, 16:9 master, 9:16 reframe, Dropbox
│   ├── gates.py          # Pre-check validators for gate views
│   ├── routing.py        # Selfie / Screen Recording / Split Screen plans
│   ├── notifications.py  # macOS osascript + Airtable status + SSE badge
│   └── recovery.py       # Orphan resume, 30-day archive rotation
│
├── modules/
│   ├── ass_writer.py     # .ASS subtitle file generation
│   ├── ffmpeg_utils.py   # FFmpeg wrappers (duration, loudnorm, reframe)
│   ├── elevenlabs_client.py
│   ├── gemini_client.py
│   └── openai_client.py  # Azure OpenAI fallback
│
├── workers/
│   └── job_runner.py     # Asyncio worker pool (concurrency = 2)
│
├── static/               # Plain HTML + HTMX — no build step
│   ├── index.html        # Jobs dashboard
│   ├── base.html
│   ├── style.css
│   └── gates/            # gate1.html – gate6.html
│
├── tests/                # pytest suite (all passing, no real credentials needed)
├── jobs/                 # Per-job working directories (auto-created)
├── archive/              # Jobs older than 30 days (auto-rotated)
├── assets/fonts/         # Inter .ttf files (add manually)
└── logs/
```

---

## Tests

```bash
pytest tests/ -v
```

All tests pass. Every external API (ElevenLabs, HeyGen, Pexels, Runway, Dropbox, Gemini) is mocked — no real credentials needed to run the suite.

---

## License

Private. All rights reserved.
