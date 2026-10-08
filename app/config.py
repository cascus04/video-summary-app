import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "small").strip()
LANGUAGE = os.getenv("LANGUAGE", "id").strip().lower()  # id | en | auto
PORT = int(os.getenv("PORT", "8765"))

SAMPLE_RATE = 16000  # Hz, format yang dipakai Whisper
