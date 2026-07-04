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
