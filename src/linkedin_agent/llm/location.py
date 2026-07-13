"""Filter jobs by location — India / remote only."""

import re
from typing import Any

_REMOTE_PATTERN = re.compile(
    r"\b(?:remote|work from home|wfh|work-from-home|fully remote|100% remote|"
    r"work from anywhere|anywhere in the world|worldwide|global remote|location independent)\b",
    re.I,
)

_INDIA_PATTERN = re.compile(
    r"\b(?:india|indian|bangalore|bengaluru|hyderabad|mumbai|pune|chennai|delhi|ncr|"
    r"gurgaon|gurugram|noida|kolkata|kochi|ahmedabad|jaipur|indore|remote india)\b",
    re.I,
)

# Explicit non-India country / onsite-abroad signals
_NON_INDIA_COUNTRY_PATTERN = re.compile(
    r"\b(?:"
    r"usa|u\.?s\.?a?\.?|united states|us[- ]based|us only|"
    r"uk|u\.?k\.?|united kingdom|london|england|"
    r"canada|toronto|vancouver|"
    r"australia|sydney|melbourne|"
    r"germany|berlin|france|paris|netherlands|amsterdam|"
    r"singapore|dubai|uae|saudi|qatar|"
    r"europe|european union|eu only|"
    r"new zealand|south africa|philippines|pakistan|bangladesh|sri lanka|nepal|"
    r"must be (?:based|located) in (?!india)|"
    r"onsite in (?!india)|"
    r"based in (?:usa|uk|u\.?s\.?|united states|canada|australia|europe|singapore|dubai)"
    r")\b",
    re.I,
)

_ONSITE_ABROAD_PATTERN = re.compile(
    r"\b(?:"
    r"on[- ]?site(?:\s+only)?|relocation required|must relocate|"
    r"visa sponsorship|work authorization (?:in|for) (?:us|uk|usa)|"
    r"only (?:us|uk|usa|canadian|australian) citizens?"
    r")\b",
    re.I,
)


def _is_remote_post(text: str, analysis: dict[str, Any]) -> bool:
    if analysis.get("is_remote") is True:
        return True
    if re.search(r"\b(?:no remote|not remote|without remote|non[- ]remote|onsite only)\b", text, re.I):
        return False
    return bool(_REMOTE_PATTERN.search(text))


def meets_location_requirement(
    post_text: str,
    analysis: dict[str, Any],
) -> tuple[bool, str]:
    """
    Return (ok_to_apply, reason_if_skipped).

    Rules:
    - Remote / WFH → apply
    - No country mentioned → apply
    - India mentioned → apply
    - Explicit non-India country (onsite) → skip
    """
    text = post_text or ""

    if _is_remote_post(text, analysis):
        return True, ""

    if analysis.get("is_india_location") is True:
        return True, ""

    if analysis.get("requires_non_india_location") is True:
        loc = analysis.get("location_requirement") or "outside India"
        return False, f"Job location outside India: {loc}"

    if _INDIA_PATTERN.search(text):
        return True, ""

    # No clear India signal — check for explicit abroad requirement
    if _NON_INDIA_COUNTRY_PATTERN.search(text):
        if not _is_remote_post(text, analysis):
            match = _NON_INDIA_COUNTRY_PATTERN.search(text)
            place = match.group(0) if match else "non-India country"
            return False, f"Explicit non-India location: {place}"

    if _ONSITE_ABROAD_PATTERN.search(text) and _NON_INDIA_COUNTRY_PATTERN.search(text):
        return False, "Onsite/relocation required outside India"

    # No location mentioned → apply
    if analysis.get("location_mentioned") is False:
        return True, ""

    mentioned = (analysis.get("location_requirement") or "").strip()
    if mentioned and not _INDIA_PATTERN.search(mentioned):
        if _NON_INDIA_COUNTRY_PATTERN.search(mentioned) and not _is_remote_post(text, analysis):
            return False, f"Location outside India: {mentioned}"

    return True, ""
