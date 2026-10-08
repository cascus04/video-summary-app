import queue
import threading
import traceback

from . import storage, summarizer, transcriber
from .config import DATA_DIR
from .recorder import pcm_to_wav

_q: queue.Queue = queue.Queue()
current: str | None = None  # id meeting yang sedang diproses


def enqueue(mid: str) -> None:
    storage.update(mid, status="queued", error=None, progress=0)
    _q.put(mid)


def _process(mid: str) -> None:
    d = DATA_DIR / mid
    wav, pcm = d / "audio.wav", d / "audio.pcm"
    if pcm.exists() and pcm.stat().st_size > 0:
        pcm_to_wav(pcm, wav)  # selalu buat ulang dari pcm (aman utk retry & recovery crash)
    if not wav.exists():
        raise RuntimeError("File audio tidak ditemukan")

    # 1) Transkripsi (dilewati bila sudah ada, mis. saat retry gagal di tahap ringkasan)
    segments = storage.load_transcript(mid)
    if not segments:
        storage.update(mid, status="transcribing", progress=0)
        segments = transcriber.transcribe(wav, on_progress=lambda p: storage.update(mid, progress=round(p, 3)))
        storage.save_transcript(mid, segments)

    # 2) Ringkasan
    storage.update(mid, status="summarizing", progress=1)
    storage.add_summary(mid, summarizer.TEMPLATES["full"][0], "", summarizer.summarize(segments))
    storage.update(mid, status="done", progress=1)


def _worker() -> None:
    global current
    while True:
        mid = _q.get()
        current = mid
        try:
            _process(mid)
        except Exception as e:
            traceback.print_exc()
            storage.update(mid, status="error", error=str(e)[:500])
        finally:
            current = None


threading.Thread(target=_worker, daemon=True).start()
