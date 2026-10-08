# Meeting Summarizer

Rekam meeting langsung dari PC Windows (suara peserta + mikrofon Anda), transkrip lokal dengan faster-whisper,
lalu ringkasan otomatis (keputusan, action items, pertanyaan terbuka) dengan Gemini. Tanpa upload manual.

## Instalasi (sekali saja)
1. Butuh Python 3.10+ dan API key Gemini (gratis dibuat di https://aistudio.google.com/apikey).
2. Klik dua kali `run.bat`. Pertama kali ia membuat `.venv` dan memasang dependensi (beberapa menit),
   lalu membuat `.env` dari `.env.example`.
3. Tutup, buka `.env`, isi `GEMINI_API_KEY=...`. Opsional: `LANGUAGE` (id/en/auto), `WHISPER_MODEL` (small/medium).
4. Jalankan lagi `run.bat`. Browser terbuka di http://localhost:8765. Model Whisper diunduh otomatis saat
   transkripsi pertama (sekitar 500 MB untuk `small`).

## Cara pakai
1. Buka `run.bat` sebelum meeting (biarkan jendela hitamnya terbuka).
2. Pakai headset/speaker PC yang sama dengan yang dipakai meeting. Beri tahu peserta bahwa meeting direkam.
3. Klik **Mulai Rekam**, lalu ikut meeting seperti biasa (Zoom / Meet / Teams / apa saja).
   Indikator hijau menunjukkan audio terdeteksi.
4. Selesai meeting, klik **Stop & Ringkas**. Status berjalan: Antre -> Transkripsi -> Meringkas -> Selesai.
   Estimasi di CPU: sekitar seperempat sampai setengah durasi meeting.
5. Klik meeting di daftar kiri untuk melihat ringkasan dan transkrip, lalu salin atau unduh `.md`.
   Judul bisa diedit langsung. Jika gagal (mis. internet putus), tekan **Coba Lagi**.

## Setelah meeting: ringkas ulang & tanya
Transkrip tersimpan, jadi Anda bisa meringkas ulang kapan saja tanpa memproses audio lagi (hanya memanggil Gemini):
- **Template**: Notulen lengkap, Ringkas singkat, Action items saja, Email follow-up. Tiap klik membuat versi baru
  (v1, v2, ...); versi lama tidak tertimpa dan bisa dipilih lewat tab atau dihapus.
- **Instruksi tambahan**: isi kotak teks sebelum klik template, mis. "fokus ke budget", "versi 5 kalimat untuk
  atasan", "tulis dalam bahasa Inggris".
- **Tanya isi meeting**: ketik pertanyaan (mis. "Kenapa launch diundur?"), jawabannya menyertakan timestamp.
- Transkrip dikirim ke Gemini sekali jalan; hanya transkrip yang sangat panjang (jauh di atas meeting biasa)
  yang dipotong.

## Tips
- Matikan notifikasi PC saat meeting (suaranya ikut terekam).
- Akurasi kurang? Ganti `WHISPER_MODEL=medium` di `.env` (lebih lambat).
- Semua data tersimpan di folder `data/` (audio, transkrip, ringkasan). Hanya teks transkrip yang dikirim ke
  Gemini API untuk diringkas; audio tidak pernah keluar dari PC.

## Keterbatasan
- Tidak membedakan pembicara.
- App harus berjalan dan suara meeting harus keluar lewat device audio PC ini.
- Jika device output berganti di tengah meeting (mis. cabut/colok headset Bluetooth), rekaman sistem bisa
  berhenti; mulai ulang rekaman.
