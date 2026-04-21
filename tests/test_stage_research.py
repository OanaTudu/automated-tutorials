"""Tests for stage_research — mocks OpenAI/Azure clients and validates research parsing."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.models import ResearchResult
from src.stage_research import (
    _cache_key,
    _parse_research,
    _run_subagents_parallel,
    research_topic,
)

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
    pipeline_config.setdefault("research", {})["parallel_subagents"] = False
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
    pipeline_config["research"]["parallel_subagents"] = False

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
    pipeline_config.setdefault("research", {})["parallel_subagents"] = False
    mock_client = MagicMock()
    mock_openai_cls.return_value = mock_client
    mock_client.responses.create.return_value = _mock_openai_response()

    out_dir = tmp_path / "nested" / "deep" / "00_research"
    result = research_topic("test topic", out_dir, pipeline_config)

    assert out_dir.exists()
    assert Path(result.output_path).parent == out_dir


# ── Phase 3: parallel subagents ──────────────────────────────────────────


def _make_parallel_config() -> dict:
    """Minimal config for exercising _run_subagents_parallel (azure provider)."""
    return {
        "research": {
            "provider": "azure_openai",
            "model": "gpt-4.1",
            "max_output_tokens": 1000,
            "max_sources": 9,
            "parallel_subagents": True,
        },
    }


@patch("src.stage_research._create_client")
def test_run_subagents_parallel_merges_results(mock_create):
    """Three distinct subagent results are merged with case-insensitive de-dup."""
    mock_create.return_value = MagicMock()

    by_name = {
        "concepts_and_prereqs": ResearchResult(
            topic="t",
            sources=["https://a.com", "https://B.com"],
            key_findings=["Concept A", "shared finding"],
            code_examples=["print(1)"],
            raw_notes="concepts notes",
        ),
        "code_examples": ResearchResult(
            topic="t",
            sources=["https://b.com"],  # duplicate of B.com (case-insensitive)
            key_findings=["snippet caption"],
            code_examples=["  print(1)  ", "print(2)"],  # first duplicate after strip
            raw_notes="code notes",
        ),
        "common_pitfalls": ResearchResult(
            topic="t",
            sources=["https://c.com"],
            key_findings=["SHARED FINDING", "Pitfall X"],  # duplicate (case-insensitive)
            code_examples=[],
            raw_notes="pitfall notes",
        ),
    }

    call_order: list[str] = []

    def _fake_azure(_client, _cfg, system_prompt, _topic):
        # Identify which subagent by a substring in the prompt.
        for name in by_name:
            # The header is shared, so we key on the "Focus exclusively on" sentence.
            if name == "concepts_and_prereqs" and "core concepts" in system_prompt:
                call_order.append(name)
                return by_name[name]
            if name == "code_examples" and "runnable code examples" in system_prompt:
                call_order.append(name)
                return by_name[name]
            if name == "common_pitfalls" and "common pitfalls" in system_prompt:
                call_order.append(name)
                return by_name[name]
        raise AssertionError(f"Unrecognised subagent prompt:\n{system_prompt}")

    with patch("src.stage_research._research_azure", side_effect=_fake_azure):
        merged = _run_subagents_parallel("t", "data scientists", _make_parallel_config())

    assert merged.topic == "t"
    # Sources: union, first-seen casing preserved.
    assert merged.sources == ["https://a.com", "https://B.com", "https://c.com"]
    # Findings: case-insensitive de-dup, first-seen casing preserved.
    assert merged.key_findings == [
        "Concept A",
        "shared finding",
        "snippet caption",
        "Pitfall X",
    ]
    # Code examples: stripped, de-duped.
    assert merged.code_examples == ["print(1)", "print(2)"]
    # Raw notes: per-subagent headers present.
    assert "## concepts_and_prereqs\nconcepts notes\n" in merged.raw_notes
    assert "## code_examples\ncode notes\n" in merged.raw_notes
    assert "## common_pitfalls\npitfall notes\n" in merged.raw_notes
    assert set(call_order) == {"concepts_and_prereqs", "code_examples", "common_pitfalls"}


@patch("src.stage_research._create_client")
def test_run_subagents_parallel_raises_on_worker_failure(mock_create):
    """When one subagent worker raises, RuntimeError is propagated with context."""
    mock_create.return_value = MagicMock()

    def _fake_azure(_client, _cfg, system_prompt, _topic):
        if "common pitfalls" in system_prompt:
            raise ValueError("boom")
        return ResearchResult(topic="t")

    with patch("src.stage_research._research_azure", side_effect=_fake_azure):
        with pytest.raises(RuntimeError, match="Subagent common_pitfalls failed:"):
            _run_subagents_parallel("t", "audience", _make_parallel_config())


def test_cache_key_distinguishes_parallel_mode():
    """Same topic/audience/cfg but different `parallel` flag → different cache keys."""
    cfg = {"model": "gpt-4.1", "max_sources": 7}
    key_serial = _cache_key("my topic", "data scientists", cfg, parallel=False)
    key_parallel = _cache_key("my topic", "data scientists", cfg, parallel=True)

    assert key_serial != key_parallel
    # Default (3-arg form) must still equal the explicit parallel=False form.
    assert _cache_key("my topic", "data scientists", cfg) == key_serial


@patch("src.stage_research._run_subagents_parallel")
@patch("src.stage_research._research_openai")
@patch("src.stage_research.OpenAI")
def test_research_topic_single_call_path_still_works(
    mock_openai_cls, mock_research_openai, mock_run_subagents, tmp_path, pipeline_config,
):
    """With parallel_subagents=False, legacy single-call dispatch is used."""
    pipeline_config["script"]["provider"] = "openai"
    pipeline_config["research"] = {"parallel_subagents": False}

    mock_openai_cls.return_value = MagicMock()
    mock_research_openai.return_value = ResearchResult(
        topic="test topic", key_findings=["legacy finding"],
    )

    result = research_topic("test topic", tmp_path / "00_research", pipeline_config)

    assert result.success is True
    mock_research_openai.assert_called_once()
    mock_run_subagents.assert_not_called()
