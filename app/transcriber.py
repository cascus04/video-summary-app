import threading
import wave
from pathlib import Path

import numpy as np

from . import config

_model = None
_lock = threading.Lock()


def _get_model():
    global _model
    with _lock:
        if _model is None:
            from faster_whisper import WhisperModel

            _model = WhisperModel(
                config.WHISPER_MODEL,
                device="cpu",
                compute_type="int8",
                cpu_threads=8,
            )
        return _model


def _load_wav(path: Path) -> np.ndarray:
    """Baca WAV 16 kHz mono int16 jadi float32; melewati dekoder PyAV bawaan faster-whisper."""
    with wave.open(str(path), "rb") as w:
        raw = w.readframes(w.getnframes())
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


def transcribe(wav_path: Path, on_progress=None) -> list[dict]:
    """Kembalikan list segmen: {start, end, text}. on_progress(fraksi 0..1)."""
    model = _get_model()
    language = None if config.LANGUAGE == "auto" else config.LANGUAGE
    segments, info = model.transcribe(
        _load_wav(wav_path),
        language=language,
        vad_filter=True,
        beam_size=5,
        condition_on_previous_text=False,
    )
    out = []
    for seg in segments:
        text = seg.text.strip()
        if text:
            out.append({"start": round(seg.start, 2), "end": round(seg.end, 2), "text": text})
        if on_progress and info.duration:
            on_progress(min(seg.end / info.duration, 1.0))
    return out
