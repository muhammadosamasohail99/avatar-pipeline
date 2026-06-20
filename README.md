# Avatar Pipeline

An AI-powered video production pipeline that takes a script from Airtable and produces a fully edited, captioned, and exported video — with a human-in-the-loop review gate at every major step.

Built with FastAPI, HTMX, ElevenLabs, HeyGen, Pexels, Google Gemini, and FFmpeg. No frontend build tooling — plain HTML/JS served by FastAPI.

---

## Overview

```
Airtable (script ready)
    └─► Voice synthesis       (ElevenLabs)
            └─► Gate 1: Audio review
    └─► Avatar generation     (HeyGen)
            └─► Gate 2: Avatar review
    └─► B-roll sourcing       (Pexels + Runway)
            └─► Gate 3: B-roll selection
    └─► Captions              (WhisperX + Gemini emphasis)
            └─► Gate 4: Caption editor
    └─► Assembly              (FFmpeg filter_complex)
            └─► Gate 5: Composite review
    └─► Export                (16:9 + 9:16 reframe, loudnorm)
            └─► Gate 6: Final review
    └─► Delivery              (Dropbox /Content/ready/)
```

Every stage is async. The app polls Airtable every 5 minutes, picks up new scripts, and processes up to 2 jobs concurrently. You review and approve at each gate through a local web UI at `http://localhost:8000`.

---

## Features

- **End-to-end automation** — from raw script to delivered video files with zero manual editing
- **6 review gates** — approve, regenerate, or edit at every major stage before the pipeline advances
- **Dual format output** — 16:9 master + 9:16 center-crop reframe generated automatically at export
- **Smart captions** — phrase-chunked subtitles with Gemini-powered emphasis highlighting
- **Multi-source B-roll** — Pexels stock footage, Runway AI-generated clips, or screen recordings
- **Format routing** — Selfie, Screen Recording, and Split Screen layouts handled automatically
- **Live dashboard** — SSE-powered job status updates, cost tracking, and macOS notifications
- **Resilient** — orphan job recovery on startup, 30-day automatic archive rotation
- **Zero build tooling** — plain HTML + HTMX frontend, no npm or bundler required

---

## Tech Stack

| Layer | Technology |
|---|---|
| API server | FastAPI + Uvicorn |
| Frontend | Plain HTML, HTMX, SSE |
| Voice synthesis | ElevenLabs |
| Avatar video | HeyGen v3 |
| B-roll (stock) | Pexels |
| B-roll (AI-generated) | Runway ML |
| Caption emphasis | Google Gemini 2.5 Flash |
| Video processing | FFmpeg |
| Job storage | Airtable |
| Delivery | Dropbox |

---

## Prerequisites

### System Dependencies

- **Python 3.11+**
- **FFmpeg** — must be on your `PATH`

  ```bash
  # macOS
  brew install ffmpeg

  # Ubuntu/Debian
  sudo apt install ffmpeg
  ```

- **WhisperX** — required for caption generation

  ```bash
  pip install whisperx
  ```

- **Inter font files** — place `.ttf` files in `assets/fonts/`
  - Download from [rsms.me/inter](https://rsms.me/inter/)

### API Keys Required

| Service | Purpose | Where to Get It |
|---|---|---|
| **Airtable** | Script source + status updates | [airtable.com](https://airtable.com) → Account → API |
| **ElevenLabs** | Voice synthesis | [elevenlabs.io](https://elevenlabs.io) → Profile → API Keys |
| **HeyGen** | AI avatar video generation | [heygen.com](https://heygen.com) → Settings → API |
| **Pexels** | Stock B-roll footage | [pexels.com/api](https://www.pexels.com/api/) |
| **Runway ML** | AI-generated B-roll | [runwayml.com](https://runwayml.com) |
| **Google Gemini** | Caption emphasis scoring | [aistudio.google.com](https://aistudio.google.com) → Get API Key |
| **Dropbox** | Delivery destination | [dropbox.com/developers](https://www.dropbox.com/developers) → Create App → OAuth2 token |

---

## Installation

```bash
git clone https://github.com/SuperDinar/avatar-pipeline-2.git
cd avatar-pipeline-2

python -m venv venv
source venv/bin/activate       # Windows: venv\Scripts\activate

pip install -r requirements.txt
```

---

## Configuration

Create a `.env` file in the project root:

```bash
touch .env
```

Then populate it:

```env
# Airtable
AIRTABLE_API_KEY=your_key_here
AIRTABLE_BASE_ID=appiE5ew3MElVDS9g
AIRTABLE_TABLE_ID=tblgfx7nmAMKIL0Km

# ElevenLabs
ELEVENLABS_API_KEY=your_key_here
ELEVENLABS_VOICE_ID=your_cloned_voice_id

# HeyGen
HEYGEN_API_KEY=your_key_here
HEYGEN_AVATAR_ID=your_trained_avatar_id

# Pexels
PEXELS_API_KEY=your_key_here

# Runway ML
RUNWAY_API_KEY=your_key_here

# Google Gemini
GEMINI_API_KEY=your_key_here
GEMINI_MODEL=gemini-2.5-flash-lite

# Dropbox
DROPBOX_TOKEN=your_oauth2_token
DROPBOX_DELIVERY_PATH=/Content/ready/
```

---

## Running the App

```bash
uvicorn main:app --reload --port 8000
```

Open `http://localhost:8000`. You'll see a live dashboard of all jobs with their current pipeline status and per-job cost.

The app auto-recovers any in-progress jobs from a previous session on startup.

---

## Seeding a Test Job

If you don't have a live Airtable script yet, seed a dummy job to inspect the UI:

```bash
python make_test_job.py
# Prints the job_id, e.g. "2026-05-16-my-test-video"
```

Then navigate to any gate directly:

```
http://localhost:8000/jobs/2026-05-16-my-test-video/gate1
http://localhost:8000/jobs/2026-05-16-my-test-video/gate2
```

---

## The 6 Review Gates

Each gate lives at `/jobs/{job_id}/gate{N}`. Review the previous stage's output, then approve, regenerate, or edit before the pipeline continues.

| Gate | Reviews | Actions |
|---|---|---|
| **Gate 1** | Voice audio — waveform, duration, silence check | Approve → avatar, Regenerate, Edit |
| **Gate 2** | Avatar video — integrity checks, frame quality | Approve → B-roll, Regenerate (max 5×) |
| **Gate 3** | B-roll grid per segment | Pick, Skip, Refresh, or Upload screen recording |
| **Gate 4** | Captions — per-word emphasis toggle, re-render preview | Re-render, Approve → assembly |
| **Gate 5** | Full composite video — flag timestamps, async re-render | Flag issues, Re-render, Approve → export |
| **Gate 6** | Final 16:9 + 9:16 side-by-side, synchronized scrub | Deliver to Dropbox |

---

## Airtable Schema

The pipeline expects these fields in your Airtable base:

| Field | Type | Notes |
|---|---|---|
| `Title` | Single line text | Used as the job slug |
| `Script` | Long text | The full video script |
| `Pipeline Status` | Single select | Pipeline writes: `Processing`, `Filming`, `Ready to Post`, `Needs Edit` |
| `Visual Format` | Single select | `Selfie`, `Screen Recording`, or `Split Screen` |

Base ID: `appiE5ew3MElVDS9g` · Table ID: `tblgfx7nmAMKIL0Km`

---

## Project Structure

```
avatar-pipeline-2/
├── main.py                  # FastAPI app, all routes, SSE live updates
├── config.py                # Settings, pipeline tuning constants
├── requirements.txt
│
├── pipeline/                # Core pipeline stages
│   ├── ingest.py            # Airtable polling, job creation, status locking
│   ├── job_state.py         # JobState, CostLedger, ActiveRegistry
│   ├── voice.py             # ElevenLabs voice synthesis
│   ├── avatar.py            # HeyGen v3 avatar generation
│   ├── broll.py             # Pexels + Runway sourcing, relevance scoring
│   ├── captions.py          # WhisperX transcription + Gemini emphasis
│   ├── assembly.py          # FFmpeg filter_complex (B-roll + caption burn-in)
│   ├── export.py            # loudnorm, 16:9 master, 9:16 reframe, Dropbox
│   ├── gates.py             # Pre-check validators for gate views
│   ├── routing.py           # Selfie / Screen Recording / Split Screen plans
│   ├── notifications.py     # macOS osascript + Airtable status + SSE badge
│   └── recovery.py          # Orphan resume on startup, 30-day archive rotation
│
├── modules/                 # Shared utilities
│   ├── ass_writer.py        # Generates .ASS subtitle files from phrase data
│   ├── ffmpeg_utils.py      # FFmpeg wrappers (duration, loudnorm, reframe)
│   ├── elevenlabs_client.py # ElevenLabs TTS API wrapper
│   ├── gemini_client.py     # Google Gemini client helper
│   └── openai_client.py     # Azure OpenAI client helper (optional fallback)
│
├── workers/
│   └── job_runner.py        # Asyncio worker pool (concurrency=2)
│
├── static/                  # Frontend (plain HTML + HTMX, no build step)
│   ├── index.html           # Jobs dashboard
│   ├── base.html            # Shared layout
│   ├── style.css
│   └── gates/               # One HTML file per review gate (gate1–gate6)
│
├── tests/                   # pytest suite — all passing
├── jobs/                    # Per-job working directories (auto-created)
├── archive/                 # Completed jobs older than 30 days (auto-rotated)
├── assets/fonts/            # Inter .ttf font files (add manually)
└── logs/
```

---

## Running Tests

```bash
pytest tests/ -v
```

All tests pass. Mocks cover all external APIs (ElevenLabs, HeyGen, Pexels, Runway, Dropbox, Gemini) — no real credentials needed to run the suite.

---

## License

Private. All rights reserved.
