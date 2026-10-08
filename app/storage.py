import json
import shutil
import sqlite3
import threading
import uuid
from datetime import datetime
from pathlib import Path

from .config import DATA_DIR

_db = sqlite3.connect(DATA_DIR / "meetings.db", check_same_thread=False)
_db.row_factory = sqlite3.Row
_lock = threading.Lock()
_db.execute(
    """CREATE TABLE IF NOT EXISTS meetings (
        id TEXT PRIMARY KEY,
        title TEXT,
        started_at TEXT,
        duration REAL DEFAULT 0,
        status TEXT,
        progress REAL DEFAULT 0,
        error TEXT
    )"""
)
_db.commit()


def meeting_dir(mid: str) -> Path:
    d = DATA_DIR / mid
    d.mkdir(exist_ok=True)
    return d


def create_meeting() -> dict:
    mid = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]
    now = datetime.now()
    title = "Meeting " + now.strftime("%d %b %Y %H:%M")
    with _lock:
        _db.execute(
            "INSERT INTO meetings (id, title, started_at, status) VALUES (?,?,?,?)",
            (mid, title, now.isoformat(timespec="seconds"), "recording"),
        )
        _db.commit()
    meeting_dir(mid)
    return get(mid)


def update(mid: str, **fields) -> None:
    if not fields:
        return
    cols = ", ".join(f"{k}=?" for k in fields)
    with _lock:
        _db.execute(f"UPDATE meetings SET {cols} WHERE id=?", (*fields.values(), mid))
        _db.commit()


def get(mid: str) -> dict | None:
    with _lock:
        row = _db.execute("SELECT * FROM meetings WHERE id=?", (mid,)).fetchone()
    return dict(row) if row else None


def list_all() -> list[dict]:
    with _lock:
        rows = _db.execute("SELECT * FROM meetings ORDER BY started_at DESC").fetchall()
    return [dict(r) for r in rows]


def delete(mid: str) -> None:
    with _lock:
        _db.execute("DELETE FROM meetings WHERE id=?", (mid,))
        _db.commit()
    shutil.rmtree(DATA_DIR / mid, ignore_errors=True)


def mark_orphans() -> None:
    """Meeting yang masih 'recording' saat app mulai berarti app sebelumnya mati mendadak."""
    with _lock:
        _db.execute("UPDATE meetings SET status='interrupted' WHERE status='recording'")
        _db.execute(
            "UPDATE meetings SET status='error', error='App ditutup saat diproses, klik Coba Lagi' "
            "WHERE status IN ('transcribing','summarizing','queued')"
        )
        _db.commit()


def save_transcript(mid: str, segments: list[dict]) -> None:
    (meeting_dir(mid) / "transcript.json").write_text(json.dumps(segments, ensure_ascii=False), encoding="utf-8")


def load_transcript(mid: str) -> list[dict]:
    p = DATA_DIR / mid / "transcript.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []


_sum_lock = threading.Lock()


def _summaries_path(mid: str) -> Path:
    return DATA_DIR / mid / "summaries.json"


def list_summaries(mid: str) -> list[dict]:
    """Semua versi ringkasan, terlama dulu. Format lama (summary.md) dimigrasi otomatis."""
    p = _summaries_path(mid)
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    old = DATA_DIR / mid / "summary.md"
    if old.exists():
        return [{"id": 1, "created": datetime.fromtimestamp(old.stat().st_mtime).isoformat(timespec="seconds"),
                 "label": "Notulen lengkap", "instruction": "", "text": old.read_text(encoding="utf-8")}]
    return []


def add_summary(mid: str, label: str, instruction: str, text: str) -> dict:
    with _sum_lock:
        items = list_summaries(mid)
        item = {
            "id": max((i["id"] for i in items), default=0) + 1,
            "created": datetime.now().isoformat(timespec="seconds"),
            "label": label,
            "instruction": instruction,
            "text": text,
        }
        items.append(item)
        meeting_dir(mid)
        _summaries_path(mid).write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
    return item


def delete_summary(mid: str, sid: int) -> None:
    with _sum_lock:
        items = [i for i in list_summaries(mid) if i["id"] != sid]
        _summaries_path(mid).write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")


def latest_summary(mid: str) -> str:
    items = list_summaries(mid)
    return items[-1]["text"] if items else ""
