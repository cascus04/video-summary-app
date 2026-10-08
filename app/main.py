from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, pipeline, storage, summarizer
from .config import DATA_DIR
from .recorder import Recorder

app = FastAPI(title="Meeting Summarizer")
recorder = Recorder()
active_id: str | None = None

storage.mark_orphans()


class TitleBody(BaseModel):
    title: str


class SummaryBody(BaseModel):
    template: str = "full"
    instruction: str = ""


class AskBody(BaseModel):
    question: str


def _need_transcript(mid: str) -> list[dict]:
    m = storage.get(mid)
    if not m:
        raise HTTPException(404, "Tidak ditemukan")
    segs = storage.load_transcript(mid)
    if not segs:
        raise HTTPException(409, "Transkrip belum tersedia")
    return segs


@app.post("/api/start")
def start():
    global active_id
    if recorder.recording:
        raise HTTPException(409, "Sudah merekam")
    m = storage.create_meeting()
    try:
        recorder.start(DATA_DIR / m["id"] / "audio.pcm")
    except Exception as e:
        storage.delete(m["id"])
        raise HTTPException(500, f"Gagal mulai rekam: {e}")
    active_id = m["id"]
    return {"id": m["id"], "warnings": recorder.warnings}


@app.post("/api/stop")
def stop():
    global active_id
    if not recorder.recording or not active_id:
        raise HTTPException(409, "Tidak sedang merekam")
    mid = active_id
    duration = recorder.stop()
    active_id = None
    storage.update(mid, duration=round(duration, 1))
    pipeline.enqueue(mid)
    return {"id": mid}


@app.get("/api/status")
def status():
    return {
        "recording": recorder.recording,
        "meeting_id": active_id,
        "elapsed": round(recorder.elapsed, 1),
        "level": round(recorder.level, 4),
        "warnings": recorder.warnings,
        "processing": pipeline.current,
        "api_key_set": bool(config.GEMINI_API_KEY),
    }


@app.get("/api/meetings")
def meetings():
    return storage.list_all()


@app.get("/api/meetings/{mid}")
def meeting(mid: str):
    m = storage.get(mid)
    if not m:
        raise HTTPException(404, "Tidak ditemukan")
    segs = storage.load_transcript(mid)
    return {**m, "summaries": storage.list_summaries(mid), "transcript": segs}


@app.get("/api/templates")
def templates():
    return [{"key": k, "label": v[0]} for k, v in summarizer.TEMPLATES.items()]


@app.post("/api/meetings/{mid}/summaries")
def new_summary(mid: str, body: SummaryBody):
    """Ringkas ulang dari transkrip yang tersimpan (tanpa Whisper); menambah versi baru."""
    segs = _need_transcript(mid)
    if body.template not in summarizer.TEMPLATES:
        raise HTTPException(400, "Template tidak dikenal")
    try:
        text = summarizer.summarize(segs, body.template, body.instruction)
    except Exception as e:
        raise HTTPException(502, f"Gagal meringkas: {e}")
    return storage.add_summary(mid, summarizer.TEMPLATES[body.template][0], body.instruction.strip(), text)


@app.delete("/api/meetings/{mid}/summaries/{sid}")
def remove_summary(mid: str, sid: int):
    if not storage.get(mid):
        raise HTTPException(404, "Tidak ditemukan")
    storage.delete_summary(mid, sid)
    return {"ok": True}


@app.post("/api/meetings/{mid}/ask")
def ask(mid: str, body: AskBody):
    segs = _need_transcript(mid)
    if not body.question.strip():
        raise HTTPException(400, "Pertanyaan kosong")
    try:
        return {"answer": summarizer.answer(segs, body.question)}
    except Exception as e:
        raise HTTPException(502, f"Gagal menjawab: {e}")


@app.patch("/api/meetings/{mid}")
def rename(mid: str, body: TitleBody):
    if not storage.get(mid):
        raise HTTPException(404, "Tidak ditemukan")
    storage.update(mid, title=body.title.strip()[:200] or "Tanpa judul")
    return {"ok": True}


@app.delete("/api/meetings/{mid}")
def remove(mid: str):
    if mid == active_id:
        raise HTTPException(409, "Meeting sedang direkam")
    storage.delete(mid)
    return {"ok": True}


@app.post("/api/meetings/{mid}/retry")
def retry(mid: str):
    m = storage.get(mid)
    if not m:
        raise HTTPException(404, "Tidak ditemukan")
    if m["status"] not in ("error", "interrupted", "done"):
        raise HTTPException(409, "Meeting sedang diproses")
    pipeline.enqueue(mid)
    return {"ok": True}


@app.get("/api/meetings/{mid}/download", response_class=PlainTextResponse)
def download(mid: str, sid: int | None = None):
    m = storage.get(mid)
    if not m:
        raise HTTPException(404, "Tidak ditemukan")
    items = storage.list_summaries(mid)
    chosen = next((i for i in items if i["id"] == sid), None) if sid else (items[-1] if items else None)
    md = f"# {m['title']}\n\n{chosen['text'] if chosen else ''}\n\n---\n\n## Transkrip\n\n"
    md += summarizer.transcript_text(storage.load_transcript(mid))
    return PlainTextResponse(
        md,
        headers={"Content-Disposition": f'attachment; filename="{mid}.md"'},
    )


STATIC = Path(__file__).parent / "static"


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
