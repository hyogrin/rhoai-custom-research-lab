"""Tests for the citation resolver pipeline.

Validates:
- Hallucinated/unknown source IDs are removed
- Repeated citations get the same number
- Citation ordering by first appearance
- Only cited sources appear in References
- N available sources never produce citation numbers > cited unique count
- Same source consistently receives the same citation number
- Works with both web sources and uploaded files
"""

import pytest

from agents.orchestrator.graph import resolve_citations, _build_source_registry


def _make_context(entries: list[dict]) -> list[dict]:
    """Helper to build accumulated_context entries with source_id."""
    result = []
    for e in entries:
        result.append({
            "source_id": e["id"],
            "document_name": e.get("name", ""),
            "source": e.get("source", ""),
            "content": e.get("content", "sample content"),
            "metadata": {
                "source_url": e.get("url", ""),
                "url": e.get("url", ""),
            },
        })
    return result


class TestSourceRegistry:
    def test_builds_from_accumulated_context(self):
        ctx = _make_context([
            {"id": "SRC_A81F", "name": "Doc A", "url": "https://a.com"},
            {"id": "SRC_B27C", "name": "Doc B", "url": ""},
        ])
        registry = _build_source_registry(ctx)
        assert "SRC_A81F" in registry
        assert "SRC_B27C" in registry
        assert registry["SRC_A81F"]["name"] == "Doc A"
        assert registry["SRC_A81F"]["url"] == "https://a.com"
        assert registry["SRC_B27C"]["url"] == ""

    def test_deduplicates_same_source_id(self):
        ctx = _make_context([
            {"id": "SRC_A81F", "name": "Doc A", "content": "chunk 1"},
            {"id": "SRC_A81F", "name": "Doc A", "content": "chunk 2"},
            {"id": "SRC_B27C", "name": "Doc B"},
        ])
        registry = _build_source_registry(ctx)
        assert len(registry) == 2


class TestResolveCitations:
    def test_basic_resolution(self):
        ctx = _make_context([
            {"id": "SRC_A81F", "name": "Doc A", "url": "https://a.com"},
            {"id": "SRC_B27C", "name": "Doc B", "url": ""},
        ])
        text = "Claim one [[cite:SRC_B27C]]. Claim two [[cite:SRC_A81F]]."
        resolved, sources = resolve_citations(text, ctx)

        assert "[[cite:" not in resolved
        assert "[1](#cite-1)" in resolved
        assert "[2](#cite-2)" in resolved
        # First appearance ordering: B27C=1, A81F=2
        assert sources[0]["name"] == "Doc B"
        assert sources[1]["name"] == "Doc A"

    def test_hallucinated_source_id_removed(self):
        ctx = _make_context([
            {"id": "SRC_A81F", "name": "Doc A"},
        ])
        text = "Valid [[cite:SRC_A81F]]. Hallucinated [[cite:SRC_FAKE]]."
        resolved, sources = resolve_citations(text, ctx)

        assert "[1](#cite-1)" in resolved
        assert "SRC_FAKE" not in resolved
        assert len(sources) == 1

    def test_repeated_citation_same_number(self):
        ctx = _make_context([
            {"id": "SRC_A81F", "name": "Doc A"},
            {"id": "SRC_B27C", "name": "Doc B"},
        ])
        text = "First [[cite:SRC_A81F]]. Second [[cite:SRC_B27C]]. Third [[cite:SRC_A81F]]."
        resolved, sources = resolve_citations(text, ctx)

        # SRC_A81F appears first → [1], SRC_B27C → [2]
        assert resolved.count("[1](#cite-1)") == 2
        assert resolved.count("[2](#cite-2)") == 1
        assert len(sources) == 2

    def test_ordering_by_first_appearance(self):
        ctx = _make_context([
            {"id": "SRC_AAA", "name": "First registered"},
            {"id": "SRC_BBB", "name": "Second registered"},
            {"id": "SRC_CCC", "name": "Third registered"},
        ])
        # Citation order in text: CCC, AAA, BBB
        text = "Intro [[cite:SRC_CCC]]. Then [[cite:SRC_AAA]]. Finally [[cite:SRC_BBB]]."
        resolved, sources = resolve_citations(text, ctx)

        assert sources[0]["name"] == "Third registered"  # CCC = [1]
        assert sources[1]["name"] == "First registered"  # AAA = [2]
        assert sources[2]["name"] == "Second registered"  # BBB = [3]

    def test_only_cited_sources_in_references(self):
        ctx = _make_context([
            {"id": "SRC_A", "name": "Cited doc"},
            {"id": "SRC_B", "name": "Uncited doc"},
            {"id": "SRC_C", "name": "Another cited"},
        ])
        text = "Statement [[cite:SRC_A]]. Another [[cite:SRC_C]]."
        _, sources = resolve_citations(text, ctx)

        assert len(sources) == 2
        names = {s["name"] for s in sources}
        assert "Cited doc" in names
        assert "Another cited" in names
        assert "Uncited doc" not in names

    def test_max_citation_number_equals_unique_cited_count(self):
        ctx = _make_context([
            {"id": "SRC_A", "name": "A"},
            {"id": "SRC_B", "name": "B"},
            {"id": "SRC_C", "name": "C"},
            {"id": "SRC_D", "name": "D"},
        ])
        # Only cite 2 of 4 sources
        text = "One [[cite:SRC_B]]. Two [[cite:SRC_D]]. Three [[cite:SRC_B]]."
        _, sources = resolve_citations(text, ctx)

        assert len(sources) == 2
        max_num = max(s["index"] for s in sources)
        assert max_num == 2  # never > unique cited count

    def test_legacy_numeric_citations_removed(self):
        ctx = _make_context([{"id": "SRC_A", "name": "A"}])
        text = "Valid [[cite:SRC_A]]. Legacy [1](#cite-1). Old [Source 5]."
        resolved, sources = resolve_citations(text, ctx)

        # Valid cite resolved, legacy formats removed
        assert "[1](#cite-1)" in resolved  # from SRC_A
        assert "[Source 5]" not in resolved
        assert len(sources) == 1

    def test_web_and_file_sources(self):
        ctx = _make_context([
            {"id": "SRC_WEB1", "name": "Web Article", "url": "https://example.com/article"},
            {"id": "SRC_FILE1", "name": "uploaded.pdf", "url": ""},
        ])
        text = "From web [[cite:SRC_WEB1]]. From file [[cite:SRC_FILE1]]."
        resolved, sources = resolve_citations(text, ctx)

        assert len(sources) == 2
        web_src = next(s for s in sources if s["name"] == "Web Article")
        file_src = next(s for s in sources if s["name"] == "uploaded.pdf")
        assert web_src["url"] == "https://example.com/article"
        assert web_src["domain"] == "example.com"
        assert file_src["url"] == ""

    def test_empty_text_returns_empty(self):
        ctx = _make_context([{"id": "SRC_A", "name": "A"}])
        resolved, sources = resolve_citations("", ctx)
        assert resolved == ""
        assert sources == []

    def test_no_citations_in_text(self):
        ctx = _make_context([{"id": "SRC_A", "name": "A"}])
        text = "No citations here."
        resolved, sources = resolve_citations(text, ctx)
        assert resolved == "No citations here."
        assert sources == []

    def test_case_insensitive_source_ids(self):
        """LLM might lowercase the source IDs — resolution should still work."""
        ctx = _make_context([
            {"id": "SRC_AB12CD", "name": "Doc A"},
            {"id": "SRC_EF34GH", "name": "Doc B"},
        ])
        text = "Lower [[cite:SRC_ab12cd]]. Mixed [[cite:SRC_Ef34Gh]]."
        resolved, sources = resolve_citations(text, ctx)

        assert "[1](#cite-1)" in resolved
        assert "[2](#cite-2)" in resolved
        assert "[[cite:" not in resolved
        assert len(sources) == 2
        assert sources[0]["name"] == "Doc A"
        assert sources[1]["name"] == "Doc B"
