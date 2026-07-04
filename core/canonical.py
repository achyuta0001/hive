"""
The Canonical Document schema.

Every connector (markdown/git today, Notion/Confluence later) must produce
objects of this exact shape. Nothing downstream of this file should ever
know or care which source a document came from.
"""

from __future__ import annotations
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class Document(BaseModel):
    id: str                      # stable id within its source (e.g. file path)
    source: str                  # "markdown" | "notion" | "confluence" | ...
    title: str
    content: str                 # plain text / markdown body, normalized
    metadata: dict = Field(default_factory=dict)   # author, tags, etc.
    permissions: list[str] = Field(default_factory=list)  # who can see this
    links: list[str] = Field(default_factory=list)         # outbound refs
    source_url: Optional[str] = None
    last_modified: Optional[datetime] = None
    content_hash: Optional[str] = None   # filled in by hash_diff.py

    def short_repr(self) -> str:
        return f"[{self.source}] {self.title} ({self.id})"
