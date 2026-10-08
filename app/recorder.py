"""Rekam audio sistem (WASAPI loopback) + mikrofon, mix jadi mono 16 kHz.

Audio ditulis bertahap ke file .pcm mentah (int16) supaya aman bila app crash,
lalu diubah jadi .wav saat Stop.
"""
import threading
import time
import wave
from collections import deque
from math import gcd
from pathlib import Path

import numpy as np
import pyaudiowpatch as pyaudio
from scipy.signal import resample_poly

from .config import SAMPLE_RATE


def pcm_to_wav(pcm_path: Path, wav_path: Path) -> None:
    with open(pcm_path, "rb") as f:
        data = f.read()
    with wave.open(str(wav_path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(data)


class _Source:
    """Satu sumber audio (loopback atau mic) yang di-resample ke 16 kHz mono."""

    def __init__(self, pa, info: dict, name: str):
        self.name = name
        self.rate = int(info["defaultSampleRate"])
        self.channels = max(1, int(info["maxInputChannels"]))
        g = gcd(SAMPLE_RATE, self.rate)
        self.up, self.down = SAMPLE_RATE // g, self.rate // g
        self.buffer: deque = deque()
        self.lock = threading.Lock()
        self.level = 0.0
        self.stream = pa.open(
            format=pyaudio.paInt16,
            channels=self.channels,
            rate=self.rate,
            input=True,
            input_device_index=info["index"],
            frames_per_buffer=1024,
            stream_callback=self._callback,
        )

    def _callback(self, in_data, frame_count, time_info, status):
        x = np.frombuffer(in_data, dtype=np.int16).astype(np.float32)
        if self.channels > 1:
            x = x.reshape(-1, self.channels).mean(axis=1)
        y = resample_poly(x, self.up, self.down) if self.rate != SAMPLE_RATE else x
        self.level = float(np.sqrt(np.mean(y**2)) / 32768.0) if len(y) else 0.0
        with self.lock:
            self.buffer.append(y)
        return (None, pyaudio.paContinue)

    def take(self, n: int) -> np.ndarray:
        """Ambil maksimal n sampel; sisanya diisi nol (loopback diam = tidak ada data)."""
        out = np.zeros(n, dtype=np.float32)
        filled = 0
        with self.lock:
            while filled < n and self.buffer:
                chunk = self.buffer.popleft()
                need = n - filled
                if len(chunk) > need:
                    self.buffer.appendleft(chunk[need:])
                    chunk = chunk[:need]
                out[filled : filled + len(chunk)] = chunk
                filled += len(chunk)
        return out

    def close(self):
        try:
            self.stream.stop_stream()
            self.stream.close()
        except Exception:
            pass


class Recorder:
    def __init__(self):
        self._pa = None
        self._sources: list[_Source] = []
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._start_time = 0.0
        self._pcm_path: Path | None = None
        self.recording = False
        self.warnings: list[str] = []

    # ---- info untuk UI ----
    @property
    def elapsed(self) -> float:
        return time.time() - self._start_time if self.recording else 0.0

    @property
    def level(self) -> float:
        return max((s.level for s in self._sources), default=0.0)

    # ---- kontrol ----
    def start(self, pcm_path: Path) -> None:
        if self.recording:
            raise RuntimeError("Sudah merekam")
        self.warnings = []
        self._pa = pyaudio.PyAudio()
        self._sources = []

        # 1) Audio sistem (suara peserta) via loopback dari output default
        try:
            wasapi = self._pa.get_host_api_info_by_type(pyaudio.paWASAPI)
            speakers = self._pa.get_device_info_by_index(wasapi["defaultOutputDevice"])
            loop = speakers
            if not speakers.get("isLoopbackDevice"):
                for dev in self._pa.get_loopback_device_info_generator():
                    if speakers["name"] in dev["name"]:
                        loop = dev
                        break
                else:
                    raise RuntimeError("Device loopback untuk output default tidak ditemukan")
            self._sources.append(_Source(self._pa, loop, "loopback"))
        except Exception as e:
            self.warnings.append(f"Audio sistem tidak bisa direkam: {e}")

        # 2) Mikrofon default (suara Anda)
        try:
            wasapi = self._pa.get_host_api_info_by_type(pyaudio.paWASAPI)
            mic = self._pa.get_device_info_by_index(wasapi["defaultInputDevice"])
            self._sources.append(_Source(self._pa, mic, "mic"))
        except Exception as e:
            self.warnings.append(f"Mikrofon tidak bisa direkam: {e}")

        if not self._sources:
            self._pa.terminate()
            raise RuntimeError("; ".join(self.warnings) or "Tidak ada sumber audio")

        self._pcm_path = pcm_path
        self._stop.clear()
        self._start_time = time.time()
        self.recording = True
        self._thread = threading.Thread(target=self._writer, daemon=True)
        self._thread.start()

    def _writer(self):
        written = 0
        with open(self._pcm_path, "ab") as f:
            while not self._stop.is_set():
                time.sleep(0.25)
                written = self._flush(f, written)
            self._flush(f, written)  # sisa terakhir

    def _flush(self, f, written: int) -> int:
        target = int((time.time() - self._start_time) * SAMPLE_RATE)
        n = target - written
        if n <= 0:
            return written
        mix = np.zeros(n, dtype=np.float32)
        for s in self._sources:
            mix += s.take(n)
        f.write(np.clip(mix, -32768, 32767).astype(np.int16).tobytes())
        f.flush()
        return written + n

    def stop(self) -> float:
        """Hentikan rekaman, kembalikan durasi (detik)."""
        if not self.recording:
            return 0.0
        duration = self.elapsed
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        for s in self._sources:
            s.close()
        self._sources = []
        if self._pa:
            self._pa.terminate()
            self._pa = None
        self.recording = False
        return duration
