"""Markdown export for the Phase 7 Authority Engine.

Produces self-contained Markdown documents for Quora answers and SEO blog
posts, and writes them to the configured export directories so they can be
published to a CMS / static site. No external services required.
"""
import os
from datetime import datetime, timezone
from typing import Optional

from app.config import settings
from app.models.quora import BlogPost, QuoraAnswer, QuoraQuestion


def _safe_filename(base: str) -> str:
    cleaned = "".join(c if c.isalnum() or c in "-_" else "-" for c in base.lower())
    cleaned = "-".join(filter(None, cleaned.split("-")))
    return cleaned or "export"


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def export_answer_markdown(question: QuoraQuestion, answer: QuoraAnswer) -> str:
    """Render a full Markdown document for a Quora answer."""
    lines = [
        f"# {question.question_text.strip()}",
        "",
        f"> Source: {question.quora_url or 'manual'}  ",
        f"> Topic: {question.topic or 'n/a'}  ",
        f"> Quality score: {answer.quality_score if answer.quality_score is not None else 'n/a'}",
        "",
        (answer.content_markdown or "").strip(),
        "",
        "---",
        f"_Exported {datetime.now(timezone.utc).isoformat()} by the Industrial "
        f"Authority Engine._",
    ]
    return "\n".join(lines).strip() + "\n"


def export_blog_markdown(blog: BlogPost) -> str:
    """Render a full SEO-ready Markdown document for a blog post."""
    lines: list = []
    if blog.meta_title:
        lines.append(f"<!-- meta_title: {blog.meta_title} -->")
    if blog.meta_description:
        lines.append(f"<!-- meta_description: {blog.meta_description} -->")
    if blog.keywords:
        lines.append(f"<!-- keywords: {blog.keywords} -->")
    lines.append("")
    lines.append(f"# {blog.title.strip()}")
    lines.append("")
    if blog.meta_description:
        lines.append(f"_{blog.meta_description.strip()}_")
        lines.append("")
    lines.append((blog.body_markdown or "").strip())
    lines.append("")
    lines.append("---")
    lines.append(
        f"_Exported {datetime.now(timezone.utc).isoformat()} — source: "
        f"{blog.source_type} #{blog.source_id}._"
    )
    return "\n".join(lines).strip() + "\n"


def write_markdown_file(
    filename: str, content: str, *, base_dir: Optional[str] = None
) -> str:
    """Write ``content`` to ``base_dir/filename.md`` and return the path."""
    base = base_dir or settings.quora_export_dir
    os.makedirs(base, exist_ok=True)
    path = os.path.join(base, f"{_safe_filename(filename)}.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)
    return path
