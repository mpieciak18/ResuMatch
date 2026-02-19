import json
import logging
import os
import uuid
from contextlib import asynccontextmanager
from datetime import date

logger = logging.getLogger(__name__)

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from .database import Base, SessionLocal, engine
from .gemini import analyze_resume
from .models import Analysis, DailyUsage

TEMPLATES_DIR = "app/templates"
MAX_PDF_BYTES = 20 * 1024 * 1024  # 20 MB (Gemini inline limit)
MIN_JOB_DESC_CHARS = 50

# --- Rate limiting ---
RATE_LIMIT_PER_IP = os.getenv("RATE_LIMIT_PER_IP", "5/hour")
DAILY_ANALYSIS_CAP = int(os.getenv("DAILY_ANALYSIS_CAP", "150"))

limiter = Limiter(key_func=get_remote_address)


async def _check_daily_cap():
    """Raise 429 if the global daily analysis cap has been reached."""
    today = date.today()
    async with SessionLocal() as session:
        usage = await session.get(DailyUsage, today)
    if usage and usage.count >= DAILY_ANALYSIS_CAP:
        raise HTTPException(
            status_code=429,
            detail="Daily analysis limit reached. Please try again tomorrow.",
        )


async def _increment_daily_counter():
    today = date.today()
    async with SessionLocal() as session:
        usage = await session.get(DailyUsage, today)
        if usage:
            usage.count += 1
        else:
            session.add(DailyUsage(usage_date=today, count=1))
        await session.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield


app = FastAPI(title="Resume Analyzer", lifespan=lifespan)
app.state.limiter = limiter
templates = Jinja2Templates(directory=TEMPLATES_DIR)


# ---------------------------------------------------------------------------
# Exception handlers
# ---------------------------------------------------------------------------


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    detail = "Rate limit exceeded. Please slow down and try again later."
    if request.headers.get("HX-Request"):
        return Response(
            content=json.dumps({"detail": detail}),
            status_code=429,
            media_type="application/json",
        )
    return templates.TemplateResponse(
        "error.html",
        {"request": request, "detail": detail, "status_code": 429},
        status_code=429,
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Return HTML error responses for HTMX requests, JSON for others."""
    if request.headers.get("HX-Request"):
        return Response(
            content=json.dumps({"detail": exc.detail}),
            status_code=exc.status_code,
            media_type="application/json",
        )
    return templates.TemplateResponse(
        "error.html",
        {"request": request, "detail": exc.detail, "status_code": exc.status_code},
        status_code=exc.status_code,
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/analyze")
@limiter.limit(RATE_LIMIT_PER_IP)
async def analyze(
    request: Request,
    resume: UploadFile = File(...),
    job_description: str = Form(...),
):
    # --- Check global daily cap ---
    await _check_daily_cap()

    # --- Validate inputs ---
    if not resume.filename or not resume.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted.")

    if len(job_description.strip()) < MIN_JOB_DESC_CHARS:
        raise HTTPException(
            status_code=400,
            detail=f"Job description must be at least {MIN_JOB_DESC_CHARS} characters.",
        )

    pdf_bytes = await resume.read()

    if len(pdf_bytes) > MAX_PDF_BYTES:
        raise HTTPException(status_code=400, detail="PDF must be under 20 MB.")

    if len(pdf_bytes) == 0:
        raise HTTPException(status_code=400, detail="Uploaded PDF is empty.")

    # --- Call Gemini ---
    try:
        result = await analyze_resume(pdf_bytes, job_description.strip())
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Unexpected error during resume analysis")
        raise HTTPException(
            status_code=502,
            detail="Analysis failed due to an upstream error. Please try again.",
        ) from exc

    await _increment_daily_counter()

    # --- Persist to DB ---
    analysis_id = str(uuid.uuid4())
    async with SessionLocal() as session:
        analysis = Analysis(
            id=analysis_id,
            resume_filename=resume.filename,
            job_description=job_description.strip(),
            score=result.score,
            summary=result.summary,
            strengths=json.dumps(result.strengths),
            weaknesses=json.dumps(result.weaknesses),
        )
        session.add(analysis)
        await session.commit()

    # --- Respond ---
    # For HTMX requests: 204 + HX-Redirect causes the browser to navigate.
    # For standard form POST: redirect normally.
    redirect_url = f"/result/{analysis_id}"
    if request.headers.get("HX-Request"):
        return Response(
            status_code=204,
            headers={"HX-Redirect": redirect_url},
        )
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url=redirect_url, status_code=303)


@app.get("/result/{analysis_id}", response_class=HTMLResponse)
async def result(request: Request, analysis_id: str):
    async with SessionLocal() as session:
        analysis = await session.get(Analysis, analysis_id)

    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found.")

    return templates.TemplateResponse(
        "result.html",
        {
            "request": request,
            "analysis": analysis,
            "strengths": json.loads(analysis.strengths),
            "weaknesses": json.loads(analysis.weaknesses),
        },
    )
