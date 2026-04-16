"""Tests for stage_script.generate_script — mocks OpenAI client and validates retry/repair."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.models import TutorialScript
from src.stage_script import generate_script

# ── Helpers ──────────────────────────────────────────────────────────────


def _valid_script_dict() -> dict:
    return {
        "topic": "python basics",
        "audience": "data scientists",
        "total_target_seconds": 240,
        "estimated_words": 500,
        "hook": (
            "Let's learn Python together in this hands-on tutorial "
            "covering the fundamentals every data scientist needs!"
        ),
        "sections": [
            {
                "id": f"s{i}",
                "title": f"Section {i}",
                "target_seconds": 60,
                "narration": (
                    f"In section {i} we will explore the important concepts "
                    "that every data scientist needs to understand for their daily "
                    "workflow including practical examples and real code demonstrations."
                ),
                "key_points": ["key concept"],
                "shots": [
                    {"id": f"s{i}-sh1", "start_sec": 0, "end_sec": 10, "visual": "v", "action": "a"}
                ],
            }
            for i in range(1, 4)
        ],
        "recap": (
            "We covered the key Python basics today including setup, "
            "variables, and functions that data scientists use daily."
        ),
        "cta": "Subscribe for more!",
    }


def _mock_response(script_dict: dict | None = None) -> MagicMock:
    """Create a mock OpenAI response with output_parsed set."""
    resp = MagicMock()
    resp.output_parsed = TutorialScript(**(script_dict or _valid_script_dict()))
    return resp


# ── Success path ─────────────────────────────────────────────────────────


@patch("src.stage_script.OpenAI")
def test_generate_script_success(mock_openai_cls, tmp_path, pipeline_config):
    mock_client = MagicMock()
    mock_openai_cls.return_value = mock_client
    mock_client.responses.parse.return_value = _mock_response()

    result = generate_script("python basics", tmp_path / "01_script", pipeline_config)

    assert result.success is True
    assert result.stage == "script"
    assert Path(result.output_path).exists()
    # Verify script.json is valid
    script = TutorialScript.model_validate_json(Path(result.output_path).read_text())
    assert script.topic == "python basics"


@patch("src.stage_script.OpenAI")
def test_generate_script_calls_responses_parse(mock_openai_cls, tmp_path, pipeline_config):
    mock_client = MagicMock()
    mock_openai_cls.return_value = mock_client
    mock_client.responses.parse.return_value = _mock_response()

    generate_script("python basics", tmp_path / "01_script", pipeline_config)

    mock_client.responses.parse.assert_called_once()
    call_kwargs = mock_client.responses.parse.call_args
    assert call_kwargs.kwargs["model"] == "gpt-4.1"
    assert call_kwargs.kwargs["text_format"] is TutorialScript


# ── Retry/repair loop ───────────────────────────────────────────────────


@patch("src.stage_script.validate_script")
@patch("src.stage_script.OpenAI")
def test_retry_on_quality_gate_failure(mock_openai_cls, mock_validate, tmp_path, pipeline_config):
    """First call fails quality gate, second succeeds → still produces output."""
    mock_client = MagicMock()
    mock_openai_cls.return_value = mock_client
    mock_client.responses.parse.return_value = _mock_response()

    # First call returns errors, second returns empty list (pass)
    mock_validate.side_effect = [["Duration exceeds cap"], []]

    result = generate_script("python basics", tmp_path / "01_script", pipeline_config)

    assert result.success is True
    assert mock_client.responses.parse.call_count == 2


@patch("src.stage_script.validate_script")
@patch("src.stage_script.OpenAI")
def test_repair_prompt_includes_error(mock_openai_cls, mock_validate, tmp_path, pipeline_config):
    """On retry, the input messages include the validation error."""
    mock_client = MagicMock()
    mock_openai_cls.return_value = mock_client
    mock_client.responses.parse.return_value = _mock_response()

    mock_validate.side_effect = [["Duration exceeds cap"], []]

    generate_script("python basics", tmp_path / "01_script", pipeline_config)

    second_call = mock_client.responses.parse.call_args_list[1]
    input_msgs = second_call.kwargs["input"]
    repair_text = input_msgs[-1]["content"]
    assert "Duration exceeds cap" in repair_text


# ── All attempts fail ────────────────────────────────────────────────────


@patch("src.stage_script.OpenAI")
def test_raises_after_all_attempts_fail(mock_openai_cls, tmp_path, pipeline_config):
    mock_client = MagicMock()
    mock_openai_cls.return_value = mock_client
    mock_client.responses.parse.side_effect = RuntimeError("API error")

    with pytest.raises(RuntimeError, match="Script generation failed"):
        generate_script("python basics", tmp_path / "01_script", pipeline_config)


@patch("src.stage_script.validate_script")
@patch("src.stage_script.OpenAI")
def test_raises_when_quality_gate_always_fails(
    mock_openai_cls, mock_validate, tmp_path, pipeline_config
):
    mock_client = MagicMock()
    mock_openai_cls.return_value = mock_client
    mock_client.responses.parse.return_value = _mock_response()

    mock_validate.return_value = ["some persistent error"]

    with pytest.raises(RuntimeError, match="Script generation failed"):
        generate_script("python basics", tmp_path / "01_script", pipeline_config)


# ── Output file ──────────────────────────────────────────────────────────


@patch("src.stage_script.OpenAI")
def test_output_dir_is_created(mock_openai_cls, tmp_path, pipeline_config):
    mock_client = MagicMock()
    mock_openai_cls.return_value = mock_client
    mock_client.responses.parse.return_value = _mock_response()

    out_dir = tmp_path / "nested" / "01_script"
    result = generate_script("python basics", out_dir, pipeline_config)

    assert out_dir.exists()
    assert Path(result.output_path).parent == out_dir


@patch("src.stage_script.OpenAI")
def test_metadata_includes_words_and_sections(mock_openai_cls, tmp_path, pipeline_config):
    mock_client = MagicMock()
    mock_openai_cls.return_value = mock_client
    mock_client.responses.parse.return_value = _mock_response()

    result = generate_script("python basics", tmp_path / "01_script", pipeline_config)

    assert result.metadata["words"] == 500
    assert result.metadata["sections"] == 3
