"""
Standalone audio capture test — no API keys needed.
Records for 10 seconds and saves to ~/.fluent/test_capture.wav

Run with:
  python test_audio.py

Then open the WAV in QuickTime or any player to verify both
mic and system audio were captured and mixed correctly.
"""

import time
import sys
from pathlib import Path

# Make sure we can import the package
sys.path.insert(0, str(Path(__file__).parent))

from fluent.audio import AudioRecorder, list_input_devices

RECORD_SECONDS = 10

print("=== Fluent audio capture test ===\n")
print("Available input devices:")
for d in list_input_devices():
    print(f"  [{d['index']}] {d['name']}  ({d['channels']}ch)")

print(f"\nRecording for {RECORD_SECONDS} seconds...")
print("Speak into your mic AND play some audio on your computer.\n")

recorder = AudioRecorder()
out_path = recorder.start()
print(f"Writing to: {out_path}")

for i in range(RECORD_SECONDS, 0, -1):
    print(f"  {i}s remaining...", end="\r", flush=True)
    time.sleep(1)

wav_path, duration = recorder.stop()
size_kb = wav_path.stat().st_size // 1024
print(f"\nDone! Recorded {duration:.1f}s  →  {wav_path}  ({size_kb} KB)")
print("\nOpen in QuickTime to verify audio quality:")
print(f"  open '{wav_path}'")
