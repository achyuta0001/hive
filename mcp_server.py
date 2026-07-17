"""
Hive MCP server — thin adapter over server/app.py, exposed as MCP tools
for Claude Code. Calls the same functions directly (same process, no
localhost HTTP hop) so there is exactly one implementation of "fetch wiki
page" and "check conflicts" behind both the HTTP API and MCP.

Register with Claude Code:
    claude mcp add hive -- python /path/to/Hive/mcp_server.py
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from server.app import (
    ConflictCheckRequest,
    check_conflicts,
    get_stats,
    get_wiki_page,
    list_wiki_pages,
)

mcp = FastMCP("hive")


@mcp.tool()
def hive_get_wiki_page(topic_slug: str) -> dict:
    """Fetch the current compiled Hive wiki page for a topic."""
    return get_wiki_page(topic_slug)


@mcp.tool()
def hive_list_topics() -> dict:
    """List all topic slugs with a compiled Hive wiki page."""
    return list_wiki_pages()


@mcp.tool()
def hive_get_stats() -> dict:
    """Cumulative cost-gate savings: docs and estimated tokens the
    hash-diff filter kept away from embeddings/LLM calls across all
    recorded sync runs."""
    return get_stats()


@mcp.tool()
def hive_check_conflicts(
    content: str, title: str, topic_slug: str, provider: str = "nvidia"
) -> dict:
    """Check whether new content conflicts with the already-compiled Hive
    wiki page for a topic. Returns has_open_conflicts + details. Does not
    modify the real compiled wiki page."""
    req = ConflictCheckRequest(content=content, title=title, topic_slug=topic_slug, provider=provider)
    return check_conflicts(req).model_dump()


if __name__ == "__main__":
    mcp.run()
