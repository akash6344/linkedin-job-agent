"""Ollama analysis — job classification and apply-info extraction."""

import json
import re
from typing import Any

import ollama

from linkedin_agent.config import MAX_YEARS_EXPERIENCE, OLLAMA_MODEL

EMAIL_PATTERN = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
FORM_PATTERN = re.compile(
    r"https?://(?:docs\.google\.com/forms/[^\s\)\]]+|forms\.gle/[^\s\)\]]+)",
    re.IGNORECASE,
)


def _parse_json(text: str) -> dict[str, Any]:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", text)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
    return {}


def analyze_post(post_text: str, search_keyword: str) -> dict[str, Any]:
    max_years = MAX_YEARS_EXPERIENCE
    prompt = f"""You analyze LinkedIn posts for job opportunities.

Search keyword used: {search_keyword}

Decide if this post is a DIRECT job opening / hiring post (not career advice, not "we're hiring 100 roles" without details, not a meme).

Experience rules for the candidate (max {max_years} years allowed):
- Extract the MINIMUM years of experience required for the role.
- If the post requires MORE than {max_years} years, set requires_more_than_max_experience to true.
- Examples: "5+ years" → min 5, skip. "3+ years" → min 3, OK. "2-4 years" → min 2, OK. "Freshers" → min 0, OK.
- If experience is not mentioned, set min_years_experience to null and requires_more_than_max_experience to false.

Also decide if this is an INTERNSHIP / trainee role (intern, internship, summer intern, trainee, apprentice). The candidate does NOT want internships.

Location rules (candidate is in India):
- If Remote / WFH / work from anywhere is offered → set is_remote true (APPLY even if another country is mentioned).
- If NO country or city is mentioned → set location_mentioned false (APPLY).
- If job is in India (India, Bangalore, Hyderabad, Mumbai, Pune, Chennai, Delhi, etc.) → set is_india_location true (APPLY).
- If job EXPLICITLY requires being in another country (US only, UK based, Canada onsite, must be in USA, etc.) WITHOUT remote → set requires_non_india_location true (SKIP).
- Do NOT skip if only the company name sounds foreign but no location is stated.

Respond with ONLY valid JSON:
{{
  "is_job_posting": true or false,
  "company": "company name or empty string",
  "job_title": "role title or empty string",
  "apply_email": "email to apply or empty string",
  "google_form_url": "full Google Form URL or empty string",
  "min_years_experience": number or null,
  "experience_requirement": "short phrase from post e.g. 5+ years or null",
  "requires_more_than_max_experience": true or false,
  "is_senior_role": true or false,
  "is_internship": true or false,
  "is_remote": true or false,
  "is_india_location": true or false,
  "location_mentioned": true or false,
  "location_requirement": "e.g. US only, Remote, Bangalore, or null",
  "requires_non_india_location": true or false,
  "confidence": 0.0 to 1.0,
  "resume_hint": "python_software" or "ai_engineer" or "unsure",
  "reason": "one short sentence"
}}

POST:
{post_text[:6000]}
"""

    try:
        response = ollama.chat(
            model=OLLAMA_MODEL,
            messages=[{"role": "user", "content": prompt}],
        )
        data = _parse_json(response["message"]["content"])
    except Exception as exc:
        return {
            "is_job_posting": False,
            "confidence": 0.0,
            "reason": f"Ollama error: {exc}",
        }

    # Regex fallback for emails/forms the model missed
    if not data.get("apply_email"):
        emails = EMAIL_PATTERN.findall(post_text)
        data["apply_email"] = emails[0] if emails else ""
    if not data.get("google_form_url"):
        forms = FORM_PATTERN.findall(post_text)
        data["google_form_url"] = forms[0] if forms else ""

    return data
