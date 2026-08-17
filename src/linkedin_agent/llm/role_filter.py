"""Deterministic role-fit filtering and job-title sanitization."""

import re
from typing import Any

# Split multi-role lists; keep "AI/ML" intact (only split on spaced "/").
_DELIMITER_PATTERN = re.compile(r"\s*(?:,|\||;|\band\b|\s/\s)\s*", re.I)

_TECH_TITLE_PATTERN = re.compile(
    r"\b(?:software|developer|engineer|programmer|full\s*stack|fullstack|"
    r"backend|front\s*end|frontend|python|java|golang|node|react|django|"
    r"flask|fastapi|devops|sre|cloud|data|machine learning|"
    r"ml|ai|genai|llm|prompt)\b",
    re.I,
)

_NON_TECH_TITLE_PATTERN = re.compile(
    r"\b(?:"
    r"sales(?:\s+(?:engineer|executive|manager|representative))?|"
    r"business development|bdm|marketing|seo|content writer|copywriter|"
    r"teacher|faculty|trainer|training|mentor|tutor|instructor|"
    r"hr|human resources|recruiter|talent acquisition|"
    r"customer support|it support|support engineer|"
    r"operations|accountant|finance|legal|"
    r"telecaller|counselor|counsellor|"
    r"filmmaker|video creator|animation artist|content creator|"
    r"prompt engineer trainer|"
    r"solar|mechanical|civil|electrical|design engineer|"
    r"estimation engineer|facility engineer|project controller|"
    r"cad\b|aem\b|odoo\b|salesforce|guidewire|"
    # QA / testing roles (do not apply)
    r"qa\b|q\.?a\.?\b|quality\s*assurance|sdet|"
    r"qa\s*(?:automation|manual|engineer|analyst|tester|lead|manager)|"
    r"(?:automation\s+)?(?:test|testing)\s*(?:engineer|analyst|developer|lead)?|"
    r"test\s*automation|manual\s*testing|software\s*tester"
    r")\b",
    re.I,
)

# Roles primarily requiring languages/stacks you don't work with.
# Skip when the title is clearly .NET / Java / C# / Laravel / PHP only.
_WRONG_STACK_TITLE = re.compile(
    r"(?:"
    r"(?:^|\W)\.net(?:\W|$)|"
    r"\bdotnet\b|\bc\s*#\b|\bcsharp\b|"
    r"(?:^|\W)asp\.net(?:\W|$)|"
    r"\bjava(?:\s+(?:developer|engineer|full[\s-]?stack|fullstack))\b|"
    r"\bj2ee\b|\bspring\s*boot(?:\s+developer)?\b|"
    r"\blaravel\b|\bphp(?:\s+developer)?\b|"
    r"\bruby\b|\brails\b|"
    r"\bangular(?:js)?(?:\s+developer)?\b|"
    r"\bios\s+developer\b|\bswift\s+developer\b|"
    r"\bandroid\s+developer\b|\bkotlin\s+developer\b|"
    r"\bflutter\s+developer\b|\bdart\s+developer\b|"
    r"\bwordpress\s+developer\b|\bdrupal\b"
    r")",
    re.I,
)

# Never apply to Java full-stack roles (even if the post also mentions React/Python).
_JAVA_FULLSTACK = re.compile(
    r"\b(?:"
    r"java[\s/,&+]*(?:spring(?:\s*boot)?[\s/,&+]*)?(?:full[\s-]?stack|fullstack)|"
    r"(?:full[\s-]?stack|fullstack)[\s/,&+]*(?:developer|engineer|dev)?[\s/,&+]*java|"
    r"j2ee[\s/,&+]*(?:full[\s-]?stack|fullstack)|"
    r"spring\s*boot[\s/,&+]*(?:full[\s-]?stack|fullstack)"
    r")\b",
    re.I,
)

# Teaching / academy noise — reject for AI roles even when "AI" appears in the title.
_AI_TEACHING_NOISE = re.compile(
    r"\b(?:"
    r"trainer|training|faculty|tutor|instructor|mentor|teacher|"
    r"academy|campus program|bootcamp|course|"
    r"filmmaker|video creator|animation|content creator"
    r")\b",
    re.I,
)

# Core AI/ML engineering titles we actually want.
_AI_CORE_TITLE = re.compile(
    r"\b(?:"
    r"(?:ai(?:\s*/\s*ml)?|ml|gen(?:erative)?\s*ai|llm|nlp|machine[\s-]?learning)"
    r"\s*(?:engineer|developer|scientist)s?|"
    r"(?:prompt|mlops|llmops)\s*(?:engineer|developer)s?|"
    r"data\s*(?:scientist|engineer)s?"
    r")\b",
    re.I,
)

_AI_CORE_POST = re.compile(
    r"\b(?:"
    r"ai engineer|ml engineer|llm engineer|genai engineer|"
    r"machine learning engineer|generative ai engineer|"
    r"prompt engineer|mlops|llmops|"
    r"data scientist|data engineer|"
    r"langchain|llamaindex|pytorch|tensorflow|hugging\s*face|"
    r"rag|fine[\s-]?tun(?:e|ing)|llm"
    r")\b",
    re.I,
)

_FULLSTACK_SIGNAL = re.compile(
    r"\b(?:"
    r"full[\s-]?stack|fullstack|"
    r"mern|mean|mevn|"
    r"react\s*(?:\+|and|/)?\s*node|"
    r"frontend\s*(?:\+|and|/)?\s*backend|"
    r"backend\s*(?:\+|and|/)?\s*frontend"
    r")\b",
    re.I,
)

_FULLSTACK_TITLE = re.compile(
    r"\b(?:"
    r"full[\s-]?stack(?:\s+(?:developer|engineer|dev))?|"
    r"fullstack(?:\s+(?:developer|engineer|dev))?|"
    r"mern(?:\s+stack)?(?:\s+(?:developer|engineer))?|"
    r"mean(?:\s+stack)?(?:\s+(?:developer|engineer))?"
    r")\b",
    re.I,
)

_ROLE_REQUIREMENTS = {
    "software_engineer": re.compile(
        r"\b(?:software|developer|engineer|backend|frontend|full[\s-]?stack|fullstack|python|mern|mean)\b",
        re.I,
    ),
    "python_developer": re.compile(
        r"\b(?:python|django|flask|fastapi|backend|api|developer|engineer|full[\s-]?stack|fullstack)\b",
        re.I,
    ),
    "backend_developer": re.compile(
        r"\b(?:backend|api|server|python|java|golang|node|developer|engineer|full[\s-]?stack|fullstack)\b",
        re.I,
    ),
    "fullstack_developer": _FULLSTACK_SIGNAL,
    "ai_engineer": _AI_CORE_POST,
    "generative_ai": _AI_CORE_POST,
}

_AI_ROLE_TAGS = frozenset({"ai_engineer", "generative_ai"})
_FULLSTACK_ROLE_TAGS = frozenset(
    {
        "software_engineer",
        "python_developer",
        "backend_developer",
        "fullstack_developer",
    }
)


def _coerce_title_text(value: Any) -> str:
    """Normalize LLM quirks (list of titles, nested dicts) into a string."""
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
                for key in ("title", "role", "job_title", "name", "value"):
                    if isinstance(item.get(key), str):
                        parts.append(item[key])
                        break
            else:
                parts.append(str(item))
        return ", ".join(p for p in parts if p.strip())
    return str(value)


def _clean_phrase(value: Any) -> str:
    text = _coerce_title_text(value)
    if not text:
        return ""
    cleaned = re.sub(r"^\s*(?:hiring|job opening|opening for)\s*[:\-]?\s*", "", text.strip(), flags=re.I)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -:|,;/")
    return cleaned


def sanitize_job_title(
    job_title: Any = None,
    fallback: str = "",
    *,
    prefer_ai: bool = False,
    prefer_fullstack: bool = False,
) -> str:
    """Pick one clean role title, never a comma-separated list."""
    text = _clean_phrase(job_title)
    if not text:
        text = _clean_phrase(re.sub(r"\bhiring\b", "", _coerce_title_text(fallback), flags=re.I))
    if not text:
        return ""

    parts = [_clean_phrase(p) for p in _DELIMITER_PATTERN.split(text) if _clean_phrase(p)]
    if not parts:
        return text

    if prefer_ai:
        ai_parts = [
            p
            for p in parts
            if _AI_CORE_TITLE.search(p) and not _AI_TEACHING_NOISE.search(p)
        ]
        if ai_parts:
            return ai_parts[0]

    if prefer_fullstack:
        fs_parts = [
            p
            for p in parts
            if _FULLSTACK_TITLE.search(p)
            and not _NON_TECH_TITLE_PATTERN.search(p)
            and not _JAVA_FULLSTACK.search(p)
        ]
        if fs_parts:
            return fs_parts[0]

    tech_parts = [
        p
        for p in parts
        if _TECH_TITLE_PATTERN.search(p) and not _NON_TECH_TITLE_PATTERN.search(p)
    ]
    if tech_parts:
        return tech_parts[0]
    return parts[0]


def meets_role_requirement(
    post_text: str,
    analysis: dict[str, Any],
    role_tag: str,
) -> tuple[bool, str]:
    """Hard filter: only apply when title/post fits selected technical role."""
    prefer_ai = role_tag in _AI_ROLE_TAGS
    prefer_fullstack = role_tag in _FULLSTACK_ROLE_TAGS and not prefer_ai
    title = sanitize_job_title(
        analysis.get("job_title") or "",
        prefer_ai=prefer_ai,
        prefer_fullstack=prefer_fullstack,
    )
    if title:
        analysis["job_title"] = title

    title_text = (analysis.get("job_title") or "").strip()
    full_text = f"{title_text}\n{post_text or ''}"

    if _NON_TECH_TITLE_PATTERN.search(title_text):
        return False, f"Role mismatch (non-tech title): {title_text}"

    if _JAVA_FULLSTACK.search(title_text) or _JAVA_FULLSTACK.search(full_text):
        return False, f"Role mismatch (Java full stack): {title_text or 'post'}"

    if _WRONG_STACK_TITLE.search(title_text):
        # Allow if the post also mentions Python/Node/React (multi-stack role).
        if not re.search(r"\b(?:python|node|react|fastapi|django|flask)\b", full_text, re.I):
            return False, f"Role mismatch (wrong stack): {title_text}"

    if prefer_ai:
        if _AI_TEACHING_NOISE.search(title_text):
            return False, f"Role mismatch (AI teaching/content): {title_text}"
        if _AI_TEACHING_NOISE.search(full_text) and not _AI_CORE_TITLE.search(title_text):
            return False, "Role mismatch: AI teaching/content post"
        if not (_AI_CORE_TITLE.search(title_text) or _AI_CORE_POST.search(full_text)):
            return False, f"Role mismatch for {role_tag}: not a core AI engineering role"

    if not _TECH_TITLE_PATTERN.search(full_text):
        return False, "Role mismatch: no strong technical role signal"

    required = _ROLE_REQUIREMENTS.get(role_tag)
    if required and not required.search(full_text):
        return False, f"Role mismatch for {role_tag}"

    return True, ""
