"""Tests for stage_critique — mocks LLM client and validates critique evaluation."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from src.models import CritiqueResult, CritiqueScores, ResearchResult
from src.stage_critique import _build_critique_prompt, _default_critique, critique_tutorial

# ── Helpers ──────────────────────────────────────────────────────────────


def _sample_research() -> ResearchResult:
    return ResearchResult(
        topic="python basics",
        key_findings=["Python is versatile"],
        sources=["https://python.org"],
        code_examples=["import pandas as pd"],
    )


def _mock_critique() -> CritiqueResult:
    return CritiqueResult(
        scores=CritiqueScores(
            accuracy=8,
            completeness=7,
            pacing=8,
            audience_fit=9,
            teaching_effectiveness=8,
        ),
        overall_grade=8.0,
        strengths=["Good hook"],
        improvements=["Add more examples"],
        summary="Solid tutorial",
    )


# ── Success path ─────────────────────────────────────────────────────────


@patch("src.stage_critique._create_client")
def test_critique_tutorial_openai_success(mock_create, sample_script, tmp_path, pipeline_config):
    """OpenAI provider produces a valid critique.json via responses.parse."""
    mock_client = MagicMock()
    mock_create.return_value = mock_client
    mock_resp = MagicMock()
    mock_resp.output_parsed = _mock_critique()
    mock_client.responses.parse.return_value = mock_resp

    result = critique_tutorial(
        sample_script, _sample_research(), tmp_path / "03_critique", pipeline_config,
    )

    assert result.success is True
    assert result.stage == "critique"
    assert Path(result.output_path).exists()

    # Verify persisted critique.json is valid
    critique = CritiqueResult.model_validate_json(Path(result.output_path).read_text())
    assert critique.overall_grade == 8.0
    assert "accuracy" in critique.scores.model_dump()


# ── Graceful failure ─────────────────────────────────────────────────────


@patch("src.stage_critique._create_client")
def test_critique_tutorial_graceful_failure(mock_create, sample_script, tmp_path, pipeline_config):
    """When the client raises, critique_tutorial returns a default CritiqueResult with grade 5.0."""
    mock_create.side_effect = RuntimeError("API unavailable")

    result = critique_tutorial(
        sample_script, _sample_research(), tmp_path / "03_critique", pipeline_config,
    )

    assert result.success is True  # critique always returns success
    assert Path(result.output_path).exists()
    critique = CritiqueResult.model_validate_json(Path(result.output_path).read_text())
    assert critique.overall_grade == 5.0
    assert "API unavailable" in critique.summary


# ── Output directory ─────────────────────────────────────────────────────


@patch("src.stage_critique._create_client")
def test_critique_creates_output_dir(mock_create, sample_script, tmp_path, pipeline_config):
    """critique_tutorial creates the output directory if it doesn't exist."""
    mock_create.side_effect = RuntimeError("skip")

    out_dir = tmp_path / "nested" / "deep" / "03_critique"
    result = critique_tutorial(
        sample_script, _sample_research(), out_dir, pipeline_config,
    )

    assert out_dir.exists()
    assert Path(result.output_path).parent == out_dir


# ── _build_critique_prompt ───────────────────────────────────────────────


def test_build_critique_prompt_includes_sections(sample_script):
    """The prompt includes each section title from the script."""
    research = _sample_research()
    prompt = _build_critique_prompt(sample_script, research, audience="data scientists")

    for section in sample_script.sections:
        assert section.title in prompt
    assert research.topic in prompt
    assert "data scientists" in prompt


# ── _default_critique ────────────────────────────────────────────────────


def test_default_critique_has_expected_scores():
    """_default_critique returns all five score dimensions at 5.0 with grade 5.0."""
    critique = _default_critique("test reason")

    assert critique.overall_grade == 5.0
    expected_keys = {"accuracy", "completeness", "pacing", "audience_fit", "teaching_effectiveness"}
    assert set(critique.scores.model_dump().keys()) == expected_keys
    assert all(v == 5.0 for v in critique.scores.model_dump().values())
    assert critique.strengths == []
    assert critique.improvements == []
    assert "test reason" in critique.summary
