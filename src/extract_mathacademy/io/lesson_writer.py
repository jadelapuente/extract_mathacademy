from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any, Callable, TextIO
from urllib.parse import urljoin, urlparse

from extract_mathacademy.mathacademy.lesson_extract import extract_steps, extract_title, slugify
from extract_mathacademy.mathacademy.render import to_json, to_markdown

# Content-Type -> file extension for the image formats Math Academy serves.
_IMG_EXT = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/svg+xml": ".svg",
    "image/webp": ".webp",
}
_MARKDOWN_IMAGE_RE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")


def image_filename(src: str, content_type: str) -> str:
    """Local filename for an image src.

    Keeps the image's own extension if present; otherwise appends the extension
    implied by Content-Type. Math Academy graphics srcs are commonly
    extensionless hashes like /graphics/<hash>.
    """
    p = Path(urlparse(src).path)
    if p.suffix:
        return p.name
    ext = _IMG_EXT.get(content_type.split(";")[0].strip(), ".img")
    return p.name + ext


def download_images(srcs, base_url: str, out_dir: Path, cookies) -> dict[str, str]:
    """Download image srcs into out_dir and return {original_src: local_name}."""
    import requests

    mapping: dict[str, str] = {}
    for src in dict.fromkeys(srcs):                 # de-dup, keep order
        r = requests.get(
            urljoin(base_url, src),
            cookies=cookies,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=30,
        )
        r.raise_for_status()
        fname = image_filename(src, r.headers.get("content-type", ""))
        (out_dir / fname).write_bytes(r.content)
        mapping[src] = fname
    return mapping


DownloadImages = Callable[[list[str], str, Path, Any], dict[str, str]]


def markdown_image_sources(markdown: str) -> list[str]:
    return _MARKDOWN_IMAGE_RE.findall(markdown)


def rewrite_markdown_image_sources(
    markdown: str,
    mapping: dict[str, str],
) -> str:
    def rewrite(match: re.Match[str]) -> str:
        src = match.group(1)
        if src not in mapping:
            return match.group(0)
        return match.group(0).replace(f"({src})", f"({mapping[src]})")

    return _MARKDOWN_IMAGE_RE.sub(rewrite, markdown)


def write_extracted_lesson(
    html: str,
    *,
    fallback_name: str,
    fmt: str,
    out_dir: Path,
    output: Path | None = None,
    source_url: str | None = None,
    cookies=None,
    no_images: bool = False,
    download_images_fn: DownloadImages = download_images,
    stderr: TextIO | None = None,
) -> tuple[Path, int]:
    stderr = stderr if stderr is not None else sys.stderr
    steps = extract_steps(html)
    if not steps:
        print("warning: no lesson steps found in input", file=stderr)

    title = extract_title(html)
    name = slugify(title) if title else fallback_name

    if fmt == "json":
        text, ext = to_json(steps), ".json"
    else:
        text, ext = to_markdown(steps, title), ".md"

    # Default layout: <out-dir>/<name>/<name>.<ext> with images alongside.
    out_path = output if output else out_dir / name / f"{name}{ext}"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Download lesson images into the same directory and rewrite references.
    if source_url and not no_images:
        srcs = markdown_image_sources(text)
        if srcs:
            mapping = download_images_fn(srcs, source_url, out_path.parent, cookies)
            text = rewrite_markdown_image_sources(text, mapping)
            print(f"downloaded {len(mapping)} image(s) -> {out_path.parent}",
                  file=stderr)

    out_path.write_text(text, encoding="utf-8")
    return out_path, len(steps)
