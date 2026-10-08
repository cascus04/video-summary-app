import time

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from . import config

# Transkrip lebih panjang dari ini (~600 ribu token) baru dipotong; di bawahnya dikirim sekali jalan.
MAX_SINGLE_CHARS = 1_500_000
CHUNK_SECONDS = 30 * 60

_LANG = {"id": "Bahasa Indonesia", "en": "English", "auto": "the same language as the transcript"}

RULES = """Aturan: jangan mengarang hal yang tidak ada di transkrip. Transkrip dibuat otomatis dan bisa mengandung salah dengar; \
jika ragu, tulis apa adanya. Tidak ada informasi pembicara, jadi jangan menebak siapa yang bicara kecuali disebut jelas."""

# key -> (label di UI, instruksi format)
TEMPLATES = {
    "full": (
        "Notulen lengkap",
        """Buat notulen dalam {lang} dengan format Markdown persis seperti ini:

## Ringkasan
(3-6 kalimat inti pembahasan)

## Poin Pembahasan
(bullet per topik utama)

## Keputusan
(bullet; tulis "Tidak ada" bila tidak ada)

## Action Items
(bullet dengan format: **PIC** - tugas - deadline bila disebut; tulis "Tidak ada" bila tidak ada)

## Pertanyaan Terbuka
(bullet; tulis "Tidak ada" bila tidak ada)""",
    ),
    "short": (
        "Ringkas singkat",
        """Buat ringkasan sangat singkat dalam {lang}: maksimal 5 kalimat, lalu satu baris "Keputusan utama:" bila ada. \
Format Markdown, tanpa heading panjang.""",
    ),
    "actions": (
        "Action items saja",
        """Dalam {lang}, daftar HANYA action items dan keputusan dalam Markdown:

## Keputusan
(bullet)

## Action Items
(bullet dengan format: **PIC** - tugas - deadline bila disebut; tulis "PIC belum jelas" bila tidak disebut)

Tulis "Tidak ada" pada bagian yang kosong.""",
    ),
    "email": (
        "Email follow-up",
        """Tulis email follow-up pasca-meeting dalam {lang}, siap kirim: baris "Subjek:", sapaan, ringkasan singkat, \
keputusan, action items (siapa, apa, kapan), dan penutup sopan. Format teks biasa/Markdown ringan.""",
    ),
}


def _fmt_time(sec: float) -> str:
    sec = int(sec)
    return f"{sec // 3600:02d}:{(sec % 3600) // 60:02d}:{sec % 60:02d}"


def transcript_text(segments: list[dict]) -> str:
    return "\n".join(f"[{_fmt_time(s['start'])}] {s['text']}" for s in segments)


def _chunks(segments: list[dict]) -> list[list[dict]]:
    out, cur, base = [], [], 0.0
    for s in segments:
        if cur and s["start"] - base > CHUNK_SECONDS:
            out.append(cur)
            cur, base = [], s["start"]
        if not cur:
            base = s["start"]
        cur.append(s)
    if cur:
        out.append(cur)
    return out


def _client() -> genai.Client:
    if not config.GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY belum diisi di file .env")
    return genai.Client(api_key=config.GEMINI_API_KEY)


def _ask(client: genai.Client, prompt: str, max_tokens: int) -> str:
    # 429 (kuota/menit) dan 5xx (Google sedang padat) biasanya sementara -> ulangi dengan jeda bertambah
    for attempt in range(6):
        try:
            resp = client.models.generate_content(
                model=config.GEMINI_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(max_output_tokens=max_tokens, temperature=0.2),
            )
            break
        except genai_errors.APIError as e:
            if e.code not in (429, 500, 502, 503, 504) or attempt == 5:
                raise
            time.sleep(min(10 * 2**attempt, 60))
    text = (resp.text or "").strip()
    if not text:
        raise RuntimeError("Gemini mengembalikan jawaban kosong (mungkin diblokir filter)")
    return text


def _lang() -> str:
    return _LANG.get(config.LANGUAGE, _LANG["auto"])


def _condense(client: genai.Client, segments: list[dict]) -> str:
    """Hanya untuk transkrip yang sangat panjang: ringkas per bagian dulu agar muat satu request."""
    parts = _chunks(segments)
    out = []
    for i, part in enumerate(parts, 1):
        prompt = (
            f"Berikut potongan transkrip meeting (bagian {i} dari {len(parts)}). Ringkas dalam {_lang()} dengan bullet rapat "
            "yang mempertahankan semua keputusan, action item (siapa, apa, kapan), angka, nama, dan pertanyaan terbuka. "
            f"Jangan mengarang.\n\nTRANSKRIP:\n{transcript_text(part)}"
        )
        out.append(f"### Bagian {i}\n{_ask(client, prompt, 4000)}")
    return "\n\n".join(out)


def _material(client: genai.Client, segments: list[dict]) -> str:
    text = transcript_text(segments)
    return text if len(text) <= MAX_SINGLE_CHARS else _condense(client, segments)


def summarize(segments: list[dict], template: str = "full", instruction: str = "") -> str:
    """Ringkas transkrip dengan template + instruksi bebas dari pengguna. Satu request ke Gemini."""
    if template not in TEMPLATES:
        raise ValueError(f"Template tidak dikenal: {template}")
    client = _client()
    if not segments:
        return "## Ringkasan\nTidak ada ucapan yang terdeteksi pada rekaman ini."

    fmt = TEMPLATES[template][1].format(lang=_lang())
    extra = ""
    if instruction.strip():
        extra = (
            "\n\nInstruksi tambahan dari pengguna (prioritaskan; boleh mengubah format di atas bila bertentangan):\n"
            + instruction.strip()[:1000]
        )
    prompt = f"Kamu adalah asisten notulen meeting. {fmt}{extra}\n\n{RULES}\n\nTRANSKRIP:\n{_material(client, segments)}"
    return _ask(client, prompt, 8000)


def answer(segments: list[dict], question: str) -> str:
    """Jawab pertanyaan tentang isi meeting berdasarkan transkrip."""
    client = _client()
    if not segments:
        return "Tidak ada transkrip untuk meeting ini."
    prompt = (
        f"Jawab pertanyaan tentang meeting berikut dalam {_lang()}, singkat dan hanya berdasarkan transkrip. "
        "Sebut timestamp [hh:mm:ss] yang relevan. Jika jawabannya tidak ada di transkrip, katakan terus terang.\n\n"
        f"{RULES}\n\nPERTANYAAN: {question.strip()[:1000]}\n\nTRANSKRIP:\n{_material(client, segments)}"
    )
    return _ask(client, prompt, 3000)
