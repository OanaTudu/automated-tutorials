"""Tests for stage_research — mocks OpenAI/Azure clients and validates research parsing."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.models import ResearchResult
from src.stage_research import _parse_research, research_topic

# ── Helpers ──────────────────────────────────────────────────────────────


def _valid_research_dict() -> dict:
    return {
        "topic": "test topic",
        "sources": ["https://example.com"],
        "key_findings": ["Finding 1"],
        "code_examples": ["print('hello')"],
        "raw_notes": "Some notes",
    }


def _mock_openai_response(research_dict: dict | None = None) -> MagicMock:
    """Create a mock OpenAI Responses API response with output_text."""
    resp = MagicMock()
    resp.output_text = json.dumps(research_dict or _valid_research_dict())
    return resp


def _mock_azure_response(research_dict: dict | None = None) -> MagicMock:
    """Create a mock Azure Chat Completions response."""
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = json.dumps(research_dict or _valid_research_dict())
    return resp


# ── Success paths ────────────────────────────────────────────────────────


@patch("src.stage_research.OpenAI")
def test_research_topic_openai_success(mock_openai_cls, tmp_path, pipeline_config):
    """OpenAI provider calls responses.create with web_search_preview tool."""
    pipeline_config["script"]["provider"] = "openai"
    mock_client = MagicMock()
    mock_openai_cls.return_value = mock_client
    mock_client.responses.create.return_value = _mock_openai_response()

    result = research_topic("test topic", tmp_path / "00_research", pipeline_config)

    assert result.success is True
    assert result.stage == "research"
    assert Path(result.output_path).exists()

    # Verify responses.create was called with web_search_preview tool
    mock_client.responses.create.assert_called_once()
    call_kwargs = mock_client.responses.create.call_args.kwargs
    tools = call_kwargs["tools"]
    assert any(t.get("type") == "web_search_preview" for t in tools)

    # Verify persisted research.json is valid
    research = ResearchResult.model_validate_json(Path(result.output_path).read_text())
    assert research.topic == "test topic"
    assert len(research.key_findings) >= 1


@patch("src.stage_research._create_client")
def test_research_topic_azure_success(mock_create, tmp_path, pipeline_config):
    """Azure provider calls chat.completions.create and returns a valid StageResult."""
    pipeline_config["script"]["provider"] = "azure_openai"
    pipeline_config.setdefault("research", {})["provider"] = "azure_openai"

    mock_client = MagicMock()
    mock_create.return_value = mock_client
    mock_client.chat.completions.create.return_value = _mock_azure_response()

    result = research_topic("test topic", tmp_path / "00_research", pipeline_config)

    assert result.success is True
    assert result.stage == "research"
    mock_client.chat.completions.create.assert_called_once()


# ── Graceful failure ─────────────────────────────────────────────────────


@patch("src.stage_research._create_client")
def test_research_topic_graceful_failure(mock_create, tmp_path, pipeline_config):
    """When the client raises, research_topic returns success=False (no crash)."""
    mock_create.side_effect = RuntimeError("API unavailable")

    result = research_topic("test topic", tmp_path / "00_research", pipeline_config)

    assert result.success is False
    assert result.stage == "research"
    # research.json should still exist with an empty-findings fallback
    assert Path(result.output_path).exists()
    research = ResearchResult.model_validate_json(Path(result.output_path).read_text())
    assert research.key_findings == []


# ── _parse_research unit tests ───────────────────────────────────────────


def test_parse_research_valid_json():
    """Valid JSON string is parsed into a ResearchResult."""
    raw = json.dumps(_valid_research_dict())
    result = _parse_research(raw, "test topic")

    assert isinstance(result, ResearchResult)
    assert result.topic == "test topic"
    assert result.sources == ["https://example.com"]
    assert result.key_findings == ["Finding 1"]


def test_parse_research_markdown_fences():
    """JSON wrapped in ```json fences is parsed correctly."""
    inner = json.dumps(_valid_research_dict())
    raw = f"```json\n{inner}\n```"
    result = _parse_research(raw, "test topic")

    assert isinstance(result, ResearchResult)
    assert result.topic == "test topic"
    assert result.key_findings == ["Finding 1"]


def test_parse_research_invalid_json_fallback():
    """Garbage text falls back to a ResearchResult with raw_notes filled."""
    raw = "This is not JSON at all!! @#$%"
    result = _parse_research(raw, "fallback topic")

    assert isinstance(result, ResearchResult)
    assert result.topic == "fallback topic"
    assert result.raw_notes == raw
    assert result.key_findings == []
    assert result.sources == []


# ── Output directory ─────────────────────────────────────────────────────


@patch("src.stage_research.OpenAI")
def test_research_creates_output_dir(mock_openai_cls, tmp_path, pipeline_config):
    """research_topic creates the output directory if it doesn't exist."""
    pipeline_config["script"]["provider"] = "openai"
    mock_client = MagicMock()
    mock_openai_cls.return_value = mock_client
    mock_client.responses.create.return_value = _mock_openai_response()

    out_dir = tmp_path / "nested" / "deep" / "00_research"
    result = research_topic("test topic", out_dir, pipeline_config)

    assert out_dir.exists()
    assert Path(result.output_path).parent == out_dir
