# reels3 — Multi-platform Reels Downloader

Backend FastAPI yang gabungin beberapa public broker untuk download Reels dari **YouTube Shorts**, **Instagram Reels**, **Facebook Reels**, dan **TikTok** — bahkan dari IP datacenter yang biasanya diblok platform.

## Cara kerja

Tiap platform punya rantai broker (fallback chain). Kalau broker pertama gagal, otomatis pindah ke berikutnya:

| Platform   | Broker chain                                  |
|------------|-----------------------------------------------|
| YouTube    | `loader.to`                                   |
| Instagram  | `loader.to` → `snapsave.app`                  |
| Facebook   | `snapsave.app` → `loader.to`                  |
| TikTok     | `tikwm.com` → `loader.to`                     |

Tidak butuh cookies, tidak butuh login, tidak butuh proxy residential. Semua dikerjakan di server.

## Stack

- **Backend**: Python 3.11+ FastAPI + httpx + Node.js (untuk decode obfuscated JS dari snapsave)
- **Frontend**: Vanilla HTML/CSS + minimal JS, no build tools

## Run lokal

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Lalu buka `frontend/index.html` di browser, atau serve dengan static server apa pun.

## Endpoints

- `POST /api/extract` — body: `{"url": "..."}` → metadata + direct download URL
- `GET /api/download?url=...` — proxy stream MP4 ke client (untuk bypass CORS)

## Deploy

Render / Railway / Fly.io support. Lihat `render.yaml`.

## Disclaimer

Project ini hanya wrapper untuk public broker yang sudah ada. Semua content tetap milik pemiliknya. Pakai untuk content yang kamu punya hak download-nya.
