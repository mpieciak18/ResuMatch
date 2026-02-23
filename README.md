# ResuMatch

**AI-powered resume scoring against real job listings.** Upload your resume, provide a job description (or just a URL), and get a detailed match analysis in seconds.

Built with FastAPI, Google Gemini 2.5 Flash, and a modern HTMX + Alpine.js frontend.

---

## How It Works

1. **Upload** your resume as a PDF
2. **Provide the job description** -- paste it directly or drop in a URL to the listing
3. **Get your score** -- Gemini analyzes the match and returns a 0-100 score with specific strengths, weaknesses, and actionable feedback

When you provide a URL, ResuMatch scrapes the page content (static pages via httpx + BeautifulSoup, JS-heavy pages via Playwright) and lets Gemini extract the job description automatically before scoring.

## Tech Stack

| Layer | Technology |
|-------|-----------|
| **Backend** | Python, FastAPI, async/await throughout |
| **AI** | Google Gemini 2.5 Flash (multimodal -- reads PDFs natively) |
| **Frontend** | HTMX, Alpine.js, Tailwind CSS |
| **Database** | PostgreSQL (Neon) via SQLAlchemy async |
| **Scraping** | httpx + BeautifulSoup (static), Playwright (JS-rendered) |
| **Rate Limiting** | slowapi (per-IP + global daily cap) |

## Architecture

```
                  +-----------+
                  |  Browser  |
                  | HTMX form |
                  +-----+-----+
                        |
                   POST /analyze
                        |
                  +-----v-----+
                  |  FastAPI   |
                  |  main.py   |
                  +--+-----+--+
                     |     |
            +--------+     +--------+
            |                       |
    +-------v-------+     +--------v--------+
    |  scraper.py   |     |   gemini.py     |
    | httpx + BS4   |     | Gemini 2.5 Flash|
    | Playwright    |     |  (multimodal)   |
    +---------------+     +---------+-------+
                                    |
                          +---------v-------+
                          |   PostgreSQL    |
                          |   (Neon)        |
                          +-----------------+
```

## Getting Started

### Prerequisites

- Python 3.9+
- A [Google Gemini API key](https://aistudio.google.com/apikey)
- A [Neon](https://neon.tech) PostgreSQL database (free tier works)

### Setup

```bash
# Clone the repo
git clone https://github.com/yourusername/resumatch.git
cd resumatch

# Create virtual environment and install dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Install Chromium for Playwright (needed for JS-heavy page scraping)
python -m playwright install chromium

# Configure environment variables
cp .env.example .env
# Edit .env with your GEMINI_API_KEY and DATABASE_URL
```

### Run

```bash
uvicorn app.main:app --reload
```

Open [http://localhost:8000](http://localhost:8000) in your browser.

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GEMINI_API_KEY` | Yes | -- | Google Gemini API key |
| `DATABASE_URL` | Yes | -- | Neon PostgreSQL connection string |
| `GEMINI_MODEL` | No | `gemini-2.5-flash` | Gemini model to use |
| `RATE_LIMIT_PER_IP` | No | `5/hour` | Per-IP rate limit |
| `DAILY_ANALYSIS_CAP` | No | `150` | Global daily analysis cap |

## Project Structure

```
app/
  main.py          # FastAPI routes and request handling
  gemini.py        # Gemini API integration and prompt engineering
  scraper.py       # URL scraping (static + JS-rendered pages)
  models.py        # SQLAlchemy ORM models
  schemas.py       # Pydantic response models
  database.py      # Async database connection setup
  templates/       # Jinja2 templates (HTMX + Alpine.js)
  static/          # Static assets
```

## License

MIT
