"""
Audio capture: records mic + system audio as two separate WAV files, then
also writes a mixed file for transcription.

Streams: mic        → session_mic_*.wav
         system     → session_sys_*.wav
         mixed      → session_*.wav  (used for transcription)

The system-audio stream is platform-specific (BlackHole on macOS, WASAPI
loopback on Windows) and is opened via `platform.open_system_capture`, which
always delivers 16 kHz mono int16 chunks — the same format as the mic — so
the mixer below is identical on every platform.
"""

import wave
import time
import threading
import tempfile
import struct
import os
from pathlib import Path
from typing import Optional
import pyaudio

from fluent import platform

RATE = 16000
CHANNELS = 1
CHUNK = 1024
FORMAT = pyaudio.paInt16


def list_input_devices() -> list[dict]:
    pa = platform.make_pyaudio()
    devices = []
    for i in range(pa.get_device_count()):
        info = pa.get_device_info_by_index(i)
        if info["maxInputChannels"] > 0:
            devices.append({"index": i, "name": info["name"], "channels": info["maxInputChannels"]})
    pa.terminate()
    return devices


def _mix_frames(a: bytes, b: bytes) -> bytes:
    shorts_a = struct.unpack(f"{len(a)//2}h", a)
    shorts_b = struct.unpack(f"{len(b)//2}h", b)
    mixed = []
    for x, y in zip(shorts_a, shorts_b):
        v = x + y
        if v > 32767:
            v = 32767
        elif v < -32768:
            v = -32768
        mixed.append(v)
    return struct.pack(f"{len(mixed)}h", *mixed)


def _open_wav(path: Path) -> wave.Wave_write:
    wf = wave.open(str(path), "wb")
    wf.setnchannels(CHANNELS)
    wf.setsampwidth(2)  # int16
    wf.setframerate(RATE)
    return wf


class RecordingPaths:
    """Paths for the three output files from a single recording session."""
    def __init__(self, mixed: Path, mic: Path, sys: Path):
        self.mixed = mixed
        self.mic = mic
        self.sys = sys


class AudioRecorder:
    def __init__(self):
        self.pa: Optional[pyaudio.PyAudio] = None
        self._mic_stream = None
        self._bh_stream = None
        self._paths: Optional[RecordingPaths] = None
        self._wave_mixed = None
        self._wave_mic = None
        self._wave_sys = None
        self._lock = threading.Lock()
        self._running = False
        self._mic_buffer: list[bytes] = []
        self._bh_buffer: list[bytes] = []
        self._mixer_thread: Optional[threading.Thread] = None
        self.start_time: Optional[float] = None

    def start(self) -> RecordingPaths:
        self.pa = platform.make_pyaudio()

        base_dir = Path.home() / ".fluent"
        base_dir.mkdir(parents=True, exist_ok=True)

        def _tmp(suffix):
            f = tempfile.NamedTemporaryFile(
                suffix=suffix, delete=False, dir=base_dir,
                prefix="session_"
            )
            p = Path(f.name)
            f.close()
            return p

        self._paths = RecordingPaths(
            mixed=_tmp(".wav"),
            mic=_tmp("_mic.wav"),
            sys=_tmp("_sys.wav"),
        )

        self._wave_mixed = _open_wav(self._paths.mixed)
        self._wave_mic   = _open_wav(self._paths.mic)
        self._wave_sys   = _open_wav(self._paths.sys)

        self._running = True
        self.start_time = time.time()

        def mic_callback(in_data, frame_count, time_info, status):
            if self._running:
                with self._lock:
                    self._mic_buffer.append(in_data)
            return (None, pyaudio.paContinue)

        # System-audio chunks arrive already normalized to 16 kHz mono int16
        # by the platform layer, so they can be buffered exactly like the mic.
        def on_system_chunk(pcm: bytes):
            if self._running and pcm:
                with self._lock:
                    self._bh_buffer.append(pcm)

        self._mic_stream = self.pa.open(
            format=FORMAT, channels=CHANNELS, rate=RATE,
            input=True, input_device_index=None,
            frames_per_buffer=CHUNK, stream_callback=mic_callback,
        )

        self._bh_stream = platform.open_system_capture(
            self.pa, on_system_chunk, RATE, CHUNK, FORMAT,
        )

        self._mixer_thread = threading.Thread(target=self._mix_loop, daemon=True)
        self._mixer_thread.start()

        return self._paths

    def _mix_loop(self):
        while self._running:
            time.sleep(0.05)
            with self._lock:
                mic_chunks = list(self._mic_buffer)
                bh_chunks  = list(self._bh_buffer)
                self._mic_buffer.clear()
                self._bh_buffer.clear()

            for chunk in mic_chunks:
                self._wave_mic.writeframes(chunk)

            if self._bh_stream is None:
                for chunk in mic_chunks:
                    self._wave_mixed.writeframes(chunk)
            else:
                for chunk in bh_chunks:
                    self._wave_sys.writeframes(chunk)
                for mic_c, bh_c in zip(mic_chunks, bh_chunks):
                    if len(mic_c) == len(bh_c):
                        self._wave_mixed.writeframes(_mix_frames(mic_c, bh_c))
                    else:
                        self._wave_mixed.writeframes(mic_c)
                for chunk in mic_chunks[len(bh_chunks):]:
                    self._wave_mixed.writeframes(chunk)

    def stop(self) -> tuple[RecordingPaths, float]:
        self._running = False

        if self._mixer_thread:
            self._mixer_thread.join(timeout=2)

        with self._lock:
            for chunk in self._mic_buffer:
                self._wave_mic.writeframes(chunk)
                self._wave_mixed.writeframes(chunk)
            self._mic_buffer.clear()
            self._bh_buffer.clear()

        for stream in (self._mic_stream, self._bh_stream):
            if stream:
                stream.stop_stream()
                stream.close()
        if self.pa:
            self.pa.terminate()

        duration = time.time() - self.start_time if self.start_time else 0.0
        for wf in (self._wave_mixed, self._wave_mic, self._wave_sys):
            if wf:
                wf.close()

        return self._paths, duration
