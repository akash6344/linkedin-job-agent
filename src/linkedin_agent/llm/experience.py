"""Filter jobs by years-of-experience and internship requirements."""

import re
from typing import Any

from linkedin_agent.config import MAX_YEARS_EXPERIENCE

# Patterns that capture minimum years required (group 1 = min years)
_MIN_YEAR_PATTERNS = [
    re.compile(r"(?:minimum|min\.?|at least|requires?)\s+(\d+)\s*\+?\s*(?:years?|yrs?)", re.I),
    re.compile(r"(\d+)\s*\+\s*(?:years?|yrs?)(?:\s+of)?(?:\s+experience)?", re.I),
    re.compile(r"(\d+)\s*-\s*(\d+)\s*(?:years?|yrs?)(?:\s+of)?(?:\s+experience)?", re.I),
    re.compile(r"(\d+)\s*(?:years?|yrs?)\s+(?:of\s+)?(?:relevant\s+)?experience", re.I),
    re.compile(r"experience\s*[:\-]?\s*(\d+)\s*\+?\s*(?:years?|yrs?)", re.I),
]

# Internship / trainee indicators
_INTERNSHIP_PATTERN = re.compile(
    r"\b(?:intern(?:ship)?s?|summer intern|winter intern|trainee|apprentice(?:ship)?|"
    r"industrial training|co-?op program)\b",
    re.I,
)


def is_internship_role(post_text: str, analysis: dict[str, Any]) -> tuple[bool, str]:
    """Return (is_internship, reason). Detects intern/trainee roles to skip."""
    if analysis.get("is_internship") is True:
        title = analysis.get("job_title") or "role"
        return True, f"Internship/trainee role ({title})"

    title = (analysis.get("job_title") or "")
    if _INTERNSHIP_PATTERN.search(title):
        return True, f"Internship keyword in title: {title}"

    # Only treat body matches as internship when the post looks intern-focused,
    # to avoid skipping posts that merely mention "we also hire interns".
    matches = _INTERNSHIP_PATTERN.findall(post_text)
    if matches:
        lowered = post_text.lower()
        strong = any(
            kw in lowered
            for kw in ("internship", "intern role", "hiring intern", "intern position", "as an intern")
        )
        if strong:
            return True, f"Internship post ({matches[0]})"

    return False, ""



def _regex_min_years(text: str) -> int | None:
    """Best-effort minimum years from post text."""
    found: list[int] = []
    for pattern in _MIN_YEAR_PATTERNS:
        for match in pattern.finditer(text):
            groups = [g for g in match.groups() if g is not None]
            if not groups:
                continue
            found.append(int(groups[0]))
    return min(found) if found else None


def meets_experience_requirement(
    post_text: str,
    analysis: dict[str, Any],
    max_years: int | None = None,
) -> tuple[bool, str]:
    """
    Return (ok_to_apply, reason_if_skipped).
    Apply when requirement is <= max_years or not stated.
  """
    limit = max_years if max_years is not None else MAX_YEARS_EXPERIENCE

    llm_min = analysis.get("min_years_experience")
    if llm_min is not None:
        try:
            llm_min = int(llm_min)
            if llm_min > limit:
                return False, f"Requires {llm_min}+ years experience (max you want: {limit})"
        except (TypeError, ValueError):
            pass

    if analysis.get("requires_more_than_max_experience") is True:
        stated = analysis.get("experience_requirement") or "above your limit"
        return False, f"Experience requirement too high: {stated}"

    regex_min = _regex_min_years(post_text)
    if regex_min is not None and regex_min > limit:
        return False, f"Post mentions {regex_min}+ years experience (max: {limit})"

    # Senior titles without explicit years — only skip if LLM flagged experience too high
    if analysis.get("is_senior_role") and analysis.get("requires_more_than_max_experience"):
        return False, "Senior role with experience above your limit"

    return True, ""
