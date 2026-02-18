import base64
import json
import os

import httpx

from .schemas import AnalysisResult

GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta"
    "/models/gemini-2.5-flash:generateContent"
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


async def analyze_resume(
    pdf_bytes: bytes,
    job_description: str,
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
                        "text": ANALYSIS_PROMPT.format(
                            job_description=job_description
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
