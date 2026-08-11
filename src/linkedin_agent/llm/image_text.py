"""Extract text from LinkedIn post images (OCR / optional vision)."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

# Cap work per post so the pipeline stays responsive.
MAX_IMAGES_PER_POST = 3
MAX_IMAGE_BYTES = 4_000_000
DOWNLOAD_TIMEOUT_SEC = 12

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


def _vision_model() -> str:
    return os.environ.get("OLLAMA_VISION_MODEL", "").strip()


def download_image(url: str) -> bytes | None:
    if not url or url.startswith("data:"):
        return None
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=DOWNLOAD_TIMEOUT_SEC) as resp:
            data = resp.read(MAX_IMAGE_BYTES + 1)
            if len(data) > MAX_IMAGE_BYTES:
                return None
            return data
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        print(f"  · Image download failed: {exc}")
        return None


def _ocr_tesseract(image_path: Path) -> str:
    binary = shutil.which("tesseract")
    if not binary:
        return ""
    try:
        result = subprocess.run(
            [binary, str(image_path), "stdout", "-l", "eng", "--psm", "6"],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return (result.stdout or "").strip()
    except Exception:
        return ""


def _ocr_ollama_vision(image_path: Path) -> str:
    model = _vision_model()
    if not model:
        return ""
    try:
        import ollama
    except ImportError:
        return ""

    prompt = (
        "Extract ALL readable text from this job posting / flyer image. "
        "Include years of experience, emails, Google Form links, location, and role title. "
        "Return plain text only, no commentary."
    )
    try:
        response = ollama.chat(
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": prompt,
                    "images": [str(image_path)],
                }
            ],
        )
        return (response.get("message") or {}).get("content", "").strip()
    except Exception as exc:
        print(f"  · Vision OCR failed ({model}): {exc}")
        return ""


def extract_text_from_image_bytes(data: bytes) -> str:
    suffix = ".jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        suffix = ".png"
    elif data[:4] == b"RIFF":
        suffix = ".webp"

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(data)
        path = Path(tmp.name)

    try:
        text = _ocr_tesseract(path)
        if len(text) >= 20:
            return text
        vision = _ocr_ollama_vision(path)
        if len(vision) > len(text):
            return vision
        return text or vision
    finally:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def extract_text_from_image_urls(urls: list[str]) -> str:
    """Download up to MAX_IMAGES_PER_POST images and OCR them."""
    chunks: list[str] = []
    for url in urls[:MAX_IMAGES_PER_POST]:
        data = download_image(url)
        if not data:
            continue
        text = extract_text_from_image_bytes(data)
        if text:
            chunks.append(text)
    return "\n\n".join(chunks).strip()


def needs_image_enrichment(post_text: str, analysis: dict[str, Any]) -> bool:
    """True when text is missing experience and/or apply contact — images may help."""
    has_email = bool((analysis.get("apply_email") or "").strip())
    has_form = bool((analysis.get("google_form_url") or "").strip())
    exp_known = (
        analysis.get("min_years_experience") is not None
        or bool(analysis.get("experience_requirement"))
        or analysis.get("requires_more_than_max_experience") is True
    )
    if not has_email and not has_form:
        return True
    if not exp_known:
        return True
    return False


def merge_image_text(post_text: str, image_text: str) -> str:
    if not image_text.strip():
        return post_text
    return (
        f"{post_text}\n\n"
        f"--- Text extracted from post image(s) ---\n"
        f"{image_text.strip()}"
    )
