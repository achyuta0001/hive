"""
Hive serving layer: a thin, long-lived FastAPI process wrapping the
existing core/ modules directly. No new business logic — this just gives
callers a way to query compiled wiki pages and check for conflicts without
paying the cost of a cold `python main.py` process + full connector
re-scan every time.
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from core.canonical import Document
from core.compiler import WIKI_DIR, compile_docs

app = FastAPI(title="Hive Serving Layer")


class ConflictCheckRequest(BaseModel):
    content: str
    title: str
    topic_slug: str
    provider: str = "nvidia"
    source: str = "adhoc"
    id: str = "adhoc-check"


class ConflictCheckResponse(BaseModel):
    has_open_conflicts: bool
    conflicts_section: str
    merged_preview: str


def _extract_section(markdown: str, heading: str) -> str:
    """Return the text of one '## heading' section, up to the next '## '."""
    start = markdown.find(heading)
    if start == -1:
        return ""
    start += len(heading)
    next_heading = markdown.find("\n## ", start)
    end = next_heading if next_heading != -1 else len(markdown)
    return markdown[start:end].strip()


def _strip_meta_sections(markdown: str) -> str:
    """Remove a compiled page's own '## Open Conflicts' and '## Sources'
    sections before feeding it back into compile_docs as a baseline
    document — otherwise the model treats it as prior output to append to
    rather than raw content to re-merge, producing duplicate headings and
    burying any new conflict under the stale one."""
    for heading in ("## Open Conflicts", "## Sources"):
        start = markdown.find(heading)
        if start == -1:
            continue
        next_heading = markdown.find("\n## ", start + len(heading))
        end = next_heading if next_heading != -1 else len(markdown)
        markdown = markdown[:start] + markdown[end:]
    return markdown.strip()


@app.get("/wiki/{topic_slug}")
def get_wiki_page(topic_slug: str) -> dict:
    path = WIKI_DIR / f"{topic_slug}.md"
    if not path.exists():
        raise HTTPException(404, f"no compiled page for topic '{topic_slug}'")
    return {"topic_slug": topic_slug, "content": path.read_text(encoding="utf-8")}


@app.get("/wiki")
def list_wiki_pages() -> dict:
    if not WIKI_DIR.exists():
        return {"topics": []}
    return {"topics": sorted(p.stem for p in WIKI_DIR.glob("*.md"))}


@app.post("/check-conflicts", response_model=ConflictCheckResponse)
def check_conflicts(req: ConflictCheckRequest) -> ConflictCheckResponse:
    existing_path = WIKI_DIR / f"{req.topic_slug}.md"
    existing_content = (
        _strip_meta_sections(existing_path.read_text(encoding="utf-8"))
        if existing_path.exists()
        else "(no prior content)"
    )

    baseline = Document(
        id=f"{req.topic_slug}-current",
        source="wiki",
        title=f"Current: {req.topic_slug}",
        content=existing_content,
    )
    candidate = Document(
        id=req.id, source=req.source, title=req.title, content=req.content,
    )

    # Reuses compile_docs' merge+validate path directly — no new
    # conflict-detection logic. Written under a scratch slug and deleted
    # right after, so a conflict-check never mutates the real wiki page.
    scratch_slug = f"_conflict_check_{req.topic_slug}"
    out_path = compile_docs([baseline, candidate], scratch_slug, provider=req.provider)
    merged = out_path.read_text(encoding="utf-8")
    out_path.unlink()

    conflicts_section = _extract_section(merged, "## Open Conflicts")
    return ConflictCheckResponse(
        has_open_conflicts="None found." not in conflicts_section,
        conflicts_section=conflicts_section,
        merged_preview=merged,
    )
