import base64
import json
import os

import httpx

from .schemas import AnalysisResult

_GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_URL = (
    f"https://generativelanguage.googleapis.com/v1beta"
    f"/models/{_GEMINI_MODEL}:generateContent"
)

ANALYSIS_PROMPT = """\
You are an expert resume analyst and hiring consultant.
You have been given a resume (as a PDF) and a job description.
Your task is to evaluate how well the resume matches the job requirements.

JOB DESCRIPTION:
{job_description}

Provide a thorough, specific analysis. Avoid generic advice — reference actual \
content from the resume and job description where possible.

Respond ONLY with valid JSON in this exact structure (no markdown, no code fences):
{{
  "score": <integer from 0 to 100>,
  "summary": "<2–3 sentence overall assessment of the match>",
  "strengths": [
    "<specific strength referenced from the resume>",
    "<specific strength>",
    ...
  ],
  "weaknesses": [
    "<specific gap or improvement area>",
    "<specific gap>",
    ...
  ]
}}

Scoring guide:
- 85–100: Excellent match, candidate is highly qualified
- 65–84: Good match, candidate meets most requirements
- 45–64: Partial match, notable gaps exist
- 0–44: Weak match, significant misalignment
"""

URL_ANALYSIS_PROMPT = """\
You are an expert resume analyst and hiring consultant.
You have been given a resume (as a PDF) and the raw text content scraped from \
a job listing webpage.

The scraped page content below may contain navigation elements, headers, footers, \
and other non-job-description text. Your first task is to identify and extract the \
actual job description from this content. Then evaluate how well the resume matches \
that job description.

SCRAPED PAGE CONTENT:
{page_content}

Instructions:
1. First, identify the job title, company, and the actual job requirements/responsibilities \
from the scraped content above. Ignore navigation, ads, and unrelated content.
2. If you cannot find a clear job description in the scraped content, set the score to 0 \
and explain in the summary that no job description was found on the page.
3. If a job description is found, evaluate the resume against it thoroughly.

Provide a thorough, specific analysis. Avoid generic advice — reference actual \
content from the resume and job description where possible.

Respond ONLY with valid JSON in this exact structure (no markdown, no code fences):
{{
  "score": <integer from 0 to 100>,
  "summary": "<2–3 sentence overall assessment of the match>",
  "strengths": [
    "<specific strength referenced from the resume>",
    "<specific strength>",
    ...
  ],
  "weaknesses": [
    "<specific gap or improvement area>",
    "<specific gap>",
    ...
  ]
}}

Scoring guide:
- 85–100: Excellent match, candidate is highly qualified
- 65–84: Good match, candidate meets most requirements
- 45–64: Partial match, notable gaps exist
- 0–44: Weak match, significant misalignment
"""


async def analyze_resume(
    pdf_bytes: bytes,
    job_description: str,
    *,
    from_url: bool = False,
) -> AnalysisResult:
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        raise ValueError("GEMINI_API_KEY is not configured.")

    pdf_b64 = base64.b64encode(pdf_bytes).decode("utf-8")

    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {
                        "inline_data": {
                            "mime_type": "application/pdf",
                            "data": pdf_b64,
                        }
                    },
                    {
                        "text": (
                            URL_ANALYSIS_PROMPT.format(page_content=job_description)
                            if from_url
                            else ANALYSIS_PROMPT.format(job_description=job_description)
                        )
                    },
                ],
            }
        ],
        "generationConfig": {
            "temperature": 0.2,
            "responseMimeType": "application/json",
        },
    }

    async with httpx.AsyncClient(timeout=90.0) as client:
        response = await client.post(
            f"{GEMINI_URL}?key={api_key}",
            json=payload,
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            # Surface the actual Gemini API error message
            try:
                detail = exc.response.json()
                msg = detail.get("error", {}).get("message", str(exc))
            except Exception:
                msg = str(exc)
            raise ValueError(f"Gemini API error ({exc.response.status_code}): {msg}") from exc

    data = response.json()

    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        result = json.loads(text)
    except (KeyError, IndexError, json.JSONDecodeError) as exc:
        raise ValueError(f"Unexpected response from Gemini API: {exc}") from exc

    return AnalysisResult(
        score=result["score"],
        summary=result["summary"],
        strengths=result.get("strengths", []),
        weaknesses=result.get("weaknesses", []),
    )
