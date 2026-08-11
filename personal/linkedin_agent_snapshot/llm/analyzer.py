"""Ollama analysis — job classification and apply-info extraction."""

import json
import re
from typing import Any

import ollama

from linkedin_agent.config import MAX_YEARS_EXPERIENCE, OLLAMA_MODEL
from linkedin_agent.llm.role_filter import sanitize_job_title

EMAIL_PATTERN = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
FORM_PATTERN = re.compile(
    r"https?://(?:docs\.google\.com/forms/[^\s\)\]]+|forms\.gle/[^\s\)\]]+)",
    re.IGNORECASE,
)
# Prefer hiring inboxes when a post lists several addresses.
_PREFERRED_LOCAL = re.compile(
    r"^(?:hr|jobs?|careers?|recruit(?:ment|er)?|talent|apply|hiring|"
    r"resume|cv|contact|info|applications?)$",
    re.IGNORECASE,
)


def is_valid_apply_email(value: str | None) -> bool:
    """True only for a single RFC-ish address (no prose, lists, or URLs)."""
    if not value or not isinstance(value, str):
        return False
    return bool(EMAIL_PATTERN.fullmatch(value.strip()))


def _coerce_email_text(value: Any) -> str:
    """Normalize LLM quirks (list / nested) into a searchable string."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple, set)):
        parts: list[str] = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                for key in ("email", "address", "value"):
                    if isinstance(item.get(key), str):
                        parts.append(item[key])
                        break
            else:
                parts.append(str(item))
        return " ".join(parts)
    return str(value)


def extract_emails(text: str | None) -> list[str]:
    """Return unique emails found in text, preserving first-seen order."""
    blob = _coerce_email_text(text)
    if not blob:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for match in EMAIL_PATTERN.findall(blob):
        key = match.lower()
        if key not in seen:
            seen.add(key)
            out.append(match)
    return out


def _pick_best_email(emails: list[str]) -> str:
    if not emails:
        return ""
    for email in emails:
        local = email.split("@", 1)[0]
        if _PREFERRED_LOCAL.match(local):
            return email
    return emails[0]


def normalize_apply_email(post_text: str, llm_value: Any = None) -> str:
    """Return one valid apply email from the post, or empty string.

    Never trusts free-text LLM output. Only addresses that actually appear in
    the post are accepted. Multi-email strings are split and the best inbox
    is chosen (hr/jobs/careers/… preferred).
    """
    post_emails = extract_emails(post_text)
    if not post_emails:
        # Post has no literal email — do not invent one from LLM prose.
        return ""

    post_set = {e.lower() for e in post_emails}
    llm_text = _coerce_email_text(llm_value)
    llm_emails = [e for e in extract_emails(llm_text) if e.lower() in post_set]

    # If the model returned a single clean address that is in the post, use it.
    if is_valid_apply_email(llm_text):
        candidate = llm_text.strip()
        if candidate.lower() in post_set:
            return candidate

    return _pick_best_email(llm_emails or post_emails)


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
  "apply_email": "ONE literal email copied from the post (user@domain), or empty string if none. Never write DM/comment instructions, names, phone numbers, URLs, or multiple emails.",
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

    # Always normalize: reject LLM prose/URLs/lists; only keep emails present in the post.
    data["apply_email"] = normalize_apply_email(post_text, data.get("apply_email"))
    prefer_ai = bool(re.search(r"\b(?:ai|genai|generative)\b", search_keyword, re.I))
    prefer_fullstack = bool(
        re.search(r"\b(?:full\s*stack|fullstack|mern|mean)\b", search_keyword, re.I)
    )
    data["job_title"] = sanitize_job_title(
        data.get("job_title"),
        search_keyword,
        prefer_ai=prefer_ai,
        prefer_fullstack=prefer_fullstack and not prefer_ai,
    )

    if not data.get("google_form_url"):
        forms = FORM_PATTERN.findall(post_text)
        data["google_form_url"] = forms[0] if forms else ""

    return data
