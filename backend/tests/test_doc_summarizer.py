"""Tests for PDF document summarization and deterministic fallback."""

from unittest.mock import patch

from app.llm import LLMUnavailableError
from app.models import DocumentPage
from app.rag.doc_summarizer import summarize_document, _build_deterministic_doc_summary


def test_summarizer_deterministic_fallback():
    pages = [
        DocumentPage(
            page_number=1,
            text="RepoLens is an advanced visual analyzer and RAG assistant for code and documents.",
            char_count=85,
        ),
        DocumentPage(
            page_number=2,
            text="Section 2 describes the vector index architecture and reciprocal rank fusion.",
            char_count=80,
        ),
    ]
    outline = [{"title": "Overview", "level": 1, "page": 1}]

    # When LLM raises LLMUnavailableError
    with patch("app.rag.doc_summarizer.generate", side_effect=LLMUnavailableError("No API key configured")):
        summary = summarize_document(pages, outline, "manual.pdf", "doc-test")

    assert summary["source"] == "deterministic"
    assert "RepoLens is an advanced visual analyzer" in summary["overview"]
    assert len(summary["suggested_questions"]) == 5
    assert len(summary["key_topics"]) >= 1


def test_summarizer_with_fake_llm():
    pages = [
        DocumentPage(page_number=1, text="Introduction to system architecture.", char_count=40),
        DocumentPage(page_number=2, text="Database and caching layer details.", char_count=40),
    ]
    outline = [{"title": "Architecture", "level": 1, "page": 1}]

    mock_json = """
    {
      "overview": "This document covers system architecture and the caching layer.",
      "key_topics": ["Architecture", "Database", "Caching"],
      "suggested_questions": [
        "What is the system architecture?",
        "How is caching handled?",
        "What database is used?",
        "What are the scaling limitations?",
        "How is data persisted?"
      ]
    }
    """

    with patch("app.rag.doc_summarizer.generate", return_value=mock_json):
        summary = summarize_document(pages, outline, "design.pdf", "doc-llm")

    assert summary["source"] == "llm"
    assert "caching layer" in summary["overview"]
    assert len(summary["suggested_questions"]) == 5
    assert "Architecture" in summary["key_topics"]
