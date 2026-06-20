"""
Seed a dummy job for UI testing — no API keys required.
Run: python make_test_job.py
Then visit: http://localhost:8000/jobs/<job_id>/gate1
"""
import json
import sys
from config import ensure_dirs
from pipeline.job_state import JobState

SAMPLE_SCRIPT = """Most people waste hours every week on tasks AI can do in seconds.
Here are five tools I use every single day that have completely changed how I work.
First, I use AI to draft all my first-pass emails and content.
Second, I automate my research with AI-powered search tools.
Third, I use AI to turn my rough notes into polished scripts like this one.
The result? I get more done in two hours than I used to in an entire day.
Stop working harder. Start working smarter. The tools exist — you just have to use them."""

SAMPLE_HOOK = "Most people waste hours every week on tasks AI can do in seconds."

def main():
    ensure_dirs()
    js = JobState.create("rec_test_001", "AI Productivity Tools", "Selfie")

    (js.folder / "script.txt").write_text(SAMPLE_SCRIPT)
    (js.folder / "hook.txt").write_text(SAMPLE_HOOK)

    # Fake voice.mp3 so Gate 1 route loads without error
    (js.folder / "voice.mp3").write_bytes(b"\xff\xfb\x00" * 100)

    # Fake alignment so silence check runs
    alignment = {
        "characters": list("Hello world this is a test"),
        "character_start_times_seconds": [i * 0.08 for i in range(26)],
        "character_end_times_seconds": [(i + 1) * 0.08 for i in range(26)],
    }
    (js.folder / "voice_alignment.json").write_text(json.dumps(alignment))

    js.data["status"] = "gate_1"
    js.save()

    print(f"\nTest job created: {js.data['job_id']}")
    print(f"\nGate URLs:")
    for i in range(1, 7):
        print(f"  Gate {i}: http://localhost:8000/jobs/{js.data['job_id']}/gate{i}")
    print(f"\nDashboard: http://localhost:8000\n")

if __name__ == "__main__":
    main()
