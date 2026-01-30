# Meeting Transcription & Summarization Backend

Upload or record meeting audio; the system transcribes it with **OpenAI Whisper**, analyzes it with **Claude Sonnet**, and returns structured JSON (summary, participants, decisions, action items, translated transcript). Output can be in **Hebrew, English, French, Spanish, or Arabic**. Export to **Word (.docx)** or **PDF** with language-aware headings and RTL support. No database or authentication.

**Tech stack:** Python 3.12, FastAPI, OpenAI Whisper API, Claude Sonnet (Anthropic), python-docx, WeasyPrint (PDF).

---

## Features

- **Multi-format audio support** — MP3, WAV, M4A, AAC, OGG, FLAC, WebM, MP4, MPEG
- **Long recording support** — Handles recordings up to 2+ hours with chunked processing
- **Browser recording** — Record directly from the frontend (WebM/WAV)
- **5 output languages** — English, Hebrew, French, Spanish, Arabic
- **Word & PDF export** — Professional documents with localized headings. PDF uses **WeasyPrint** (HTML → PDF) so Hebrew, Arabic, and Latin scripts render correctly with embedded fonts (no ■■■■ squares).
- **RTL support** — Proper right-to-left formatting for Hebrew and Arabic
- **Language-aware filenames** — `meeting_summary_he.docx`
- **Robust JSON parsing** — Automatic JSON repair for reliable AI output
- **Environment-based configuration** — Production-ready with env vars

---

## Architecture

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Upload    │     │   Whisper   │     │   Claude    │     │   Export    │
│  or Record  │ ──▶ │ Transcribe  │ ──▶ │  Analyze    │ ──▶ │ Word / PDF  │
└─────────────┘     └─────────────┘     └─────────────┘     └─────────────┘
     audio              text            JSON + i18n         .docx / .pdf
```

1. **Whisper:** Audio → plain-text transcript (language-agnostic).
2. **Claude:** Transcript + target language → summary, participants, decisions, action items, **translated_transcript** (all in chosen language).
   - For long transcripts (>20k characters), uses **chunked map-reduce processing** for reliability.
   - Includes automatic JSON repair fallback if parsing fails.
3. **Document export:** Uses `translated_transcript` and analysis; headings and content in selected language with RTL support. Exports include both clean/translated transcript and full original transcript.

---

## Supported Audio Formats

| Format | Extension | Common Use |
|--------|-----------|------------|
| MP3 | `.mp3` | Universal, good compression |
| WAV | `.wav` | Uncompressed, high quality |
| M4A | `.m4a` | Apple devices, AAC |
| AAC | `.aac` | Advanced audio codec |
| OGG | `.ogg` | Open source (Vorbis/Opus) |
| FLAC | `.flac` | Lossless compression |
| WebM | `.webm` | Browser recordings |
| MP4 | `.mp4` | Video format (audio track) |
| MPEG | `.mpeg`, `.mpg` | Legacy MPEG audio/video |

---

## Supported Output Languages

| Code | Language | RTL |
|------|----------|-----|
| `en` | English | No |
| `he` | Hebrew | Yes |
| `fr` | French | No |
| `es` | Spanish | No |
| `ar` | Arabic | Yes |

Select via the `language` form field (default `en`). Affects:
- Summary and transcript language
- Document section headings
- Text direction (LTR/RTL)
- Filename suffix

---

## Local Setup

Python 3.12+ recommended.

1. **Clone** the repo and `cd` into `backend/`.
2. **Install:** `pip install -r requirements.txt`
3. **Env:** Copy `.env.example` to `.env` and set your API keys:
   ```bash
   cp .env.example .env
   # Edit .env with your keys
   ```
4. **Run:** `uvicorn app.main:app --reload`
5. **Check:** http://127.0.0.1:8000/docs (Swagger) or http://127.0.0.1:8000/api/health

### Windows: PDF export (WeasyPrint)

PDF export uses **WeasyPrint**, which needs **Pango** and its dependencies. On Windows these are not installed by default. To enable PDF export:

1. Install [MSYS2](https://www.msys2.org/#installation) (default options).
2. In the MSYS2 shell, run: `pacman -S mingw-w64-x86_64-pango`
3. Close MSYS2. In your normal terminal (where you run the backend), set the DLL path before starting the server:
   ```bash
   set WEASYPRINT_DLL_DIRECTORIES=C:\msys64\mingw64\bin
   uvicorn app.main:app --reload
   ```
   (Adjust the path if MSYS2 is installed elsewhere.)
4. Optionally add `WEASYPRINT_DLL_DIRECTORIES` to your `.env` (see `.env.example`).

Without this, the app starts and all endpoints work except PDF export; calling export-pdf returns 503 with setup instructions. See [WeasyPrint — Windows](https://doc.courtbouillon.org/weasyprint/stable/first_steps.html#windows).

---

## Environment Variables

All configuration is via environment variables (see `.env.example`):

| Variable | Description | Default |
|----------|-------------|---------|
| `APP_ENV` | Environment (development/production) | `development` |
| `APP_HOST` | Server bind address | `0.0.0.0` |
| `APP_PORT` | Server port | `8000` |
| `CORS_ORIGINS` | Comma-separated allowed origins | `http://localhost:5173,...` |
| `OPENAI_API_KEY` | OpenAI API key for Whisper | (required) |
| `ANTHROPIC_API_KEY` | Anthropic API key for Claude | (required) |

**Example `.env` for production:**
```bash
APP_ENV=production
APP_HOST=0.0.0.0
APP_PORT=8000
CORS_ORIGINS=https://speechi.adirg.dev
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
```

---

## Production Deployment

### URLs
- **Frontend:** https://speechi.adirg.dev (served by Nginx/CDN)
- **Backend API:** https://speechi.adirg.dev/api (reverse proxy to FastAPI)

### Server Setup

```bash
# Install dependencies
pip install -r requirements.txt

# Create production .env
cp .env.example .env
# Edit with production values:
# - APP_ENV=production
# - CORS_ORIGINS=https://speechi.adirg.dev
# - API keys

# Run with uvicorn
uvicorn app.main:app --host 0.0.0.0 --port 8000

# Or with gunicorn (recommended for production)
gunicorn app.main:app -w 4 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000
```

### Nginx Configuration (Example)

```nginx
server {
    listen 443 ssl;
    server_name speechi.adirg.dev;

    # SSL configuration...

    # Frontend (static files)
    location / {
        root /var/www/speechi/frontend/dist;
        try_files $uri $uri/ /index.html;
    }

    # Backend API (reverse proxy)
    location /api {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # Large file uploads
        client_max_body_size 100M;
        proxy_read_timeout 300s;
    }
}
```

### Docker (Optional)

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

---

## API Endpoints

### `GET /api/health`
Liveness check.

### `GET /api/supported-formats`
Returns list of supported audio formats.

```json
{
  "formats": ["aac", "flac", "m4a", "mp3", "mp4", "ogg", "wav", "webm"],
  "description": "AAC, FLAC, M4A, MP3, MP4, OGG, WAV, WEBM"
}
```

### `POST /api/process-meeting`
Upload audio, get JSON analysis.

**Form data:**
- `audio` (file, required) — Audio file in any supported format
- `language` (string, optional) — Output language code (default: `en`)

**Response:**
```json
{
  "transcript": "raw whisper output...",
  "analysis": {
    "summary": "Meeting summary in selected language...",
    "participants": ["Person A", "Person B"],
    "decisions": ["Decision 1", "Decision 2"],
    "action_items": [
      {"description": "Task description", "owner": "Person A"}
    ],
    "translated_transcript": "Clean transcript in selected language...",
    "raw_transcript": "Original Whisper transcript (always full)...",
    "language": "en",
    "is_condensed": false
  }
}
```

**Long recording handling:**
- For recordings over ~20k characters of transcript, the system uses chunked processing.
- `raw_transcript` always contains the full original Whisper output.
- `translated_transcript` may be condensed for very long recordings (indicated by `is_condensed: true`).
- Processing time scales with recording length; 2-hour recordings may take a few minutes.

### `POST /api/process-meeting/export-docx`
Upload audio, get Word document.

**Form data:** Same as `/process-meeting`

**Response:** `.docx` file download (`meeting_summary_{lang}.docx`)

### `POST /api/process-meeting/export-pdf`
Upload audio, get PDF document.

**Form data:** Same as `/process-meeting`

**Response:** `.pdf` file download (`meeting_summary_{lang}.pdf`)

PDF export uses **WeasyPrint** (HTML → PDF) so that Hebrew, Arabic, English, French, and Spanish render correctly. Fonts (Heebo, Noto Sans Arabic, Noto Sans) can be placed in `app/assets/fonts/` for embedding; see `app/assets/fonts/README.md`. RTL is applied for Hebrew and Arabic via `dir="rtl"` and CSS.

---

## End-to-End Tests

**JSON endpoint:**
```bash
curl -X POST -F "audio=@meeting.mp3" -F "language=en" \
  http://127.0.0.1:8000/api/process-meeting
```

**Word export (Hebrew):**
```bash
curl -X POST -F "audio=@meeting.mp3" -F "language=he" \
  http://127.0.0.1:8000/api/process-meeting/export-docx \
  --output meeting_summary_he.docx
```

**PDF export (Arabic):**
```bash
curl -X POST -F "audio=@meeting.mp3" -F "language=ar" \
  http://127.0.0.1:8000/api/process-meeting/export-pdf \
  --output meeting_summary_ar.pdf
```

---

## Project Structure

```
backend/
├── app/
│   ├── api/
│   │   └── routes.py         # HTTP endpoints
│   ├── config/
│   │   └── settings.py       # Environment config
│   ├── models/
│   │   └── schemas.py        # Pydantic models
│   ├── prompts/
│   │   └── meeting_summary_prompt.txt
│   ├── assets/
│   │   └── fonts/                    # Optional: Heebo, Noto Sans (see README)
│   ├── services/
│   │   ├── transcription_service.py  # Whisper
│   │   ├── summarization_service.py  # Claude
│   │   ├── document_service.py       # Word (.docx)
│   │   └── pdf_service.py            # PDF (WeasyPrint: HTML → PDF)
│   ├── utils/
│   │   ├── file_utils.py      # Temp files, validation
│   │   ├── document_labels.py # i18n for documents
│   │   └── env_utils.py       # Environment helpers
│   └── main.py
├── .env.example              # Environment template
├── requirements.txt
├── md.PROCESS                # Implementation docs
└── README.md
```

---

## Dependencies

```
fastapi>=0.128.0
uvicorn[standard]>=0.40.0
python-dotenv>=1.2.1
pydantic>=2.12.5
pydantic-settings>=2.12.0
openai>=2.15.0
anthropic>=0.76.0
python-multipart>=0.0.22
python-docx>=1.2.0
weasyprint>=62.0
```

See `requirements.txt` for full list. **PDF export** uses WeasyPrint (HTML → PDF) so Hebrew and Arabic render correctly with embedded fonts; generation is handled by `pdf_service`.
