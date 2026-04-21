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

    # With the plan-execute-review pipeline, the planner is called first; when the
    # mock returns a TutorialScript (not a TutorialOutline) the planner step fails
    # and we fall back to the single-call path. The final TutorialScript call must
    # therefore appear among the recorded calls.
    assert mock_client.responses.parse.called
    models_used = {c.kwargs["model"] for c in mock_client.responses.parse.call_args_list}
    text_formats = {c.kwargs.get("text_format") for c in mock_client.responses.parse.call_args_list}
    assert "gpt-4.1" in models_used
    assert TutorialScript in text_formats


# ── Retry/repair loop ───────────────────────────────────────────────────


@patch("src.stage_script._plan_outline", side_effect=RuntimeError("planner unavailable"))
@patch("src.stage_script.validate_script")
@patch("src.stage_script.OpenAI")
def test_retry_on_quality_gate_failure(
    mock_openai_cls, mock_validate, _mock_plan, tmp_path, pipeline_config,
):
    """Single-call fallback path: first call fails quality gate, second succeeds."""
    mock_client = MagicMock()
    mock_openai_cls.return_value = mock_client
    mock_client.responses.parse.return_value = _mock_response()

    # First call returns errors, second returns empty list (pass)
    mock_validate.side_effect = [["Duration exceeds cap"], []]

    result = generate_script("python basics", tmp_path / "01_script", pipeline_config)

    assert result.success is True
    assert mock_client.responses.parse.call_count == 2


@patch("src.stage_script._plan_outline", side_effect=RuntimeError("planner unavailable"))
@patch("src.stage_script.validate_script")
@patch("src.stage_script.OpenAI")
def test_repair_prompt_includes_error(
    mock_openai_cls, mock_validate, _mock_plan, tmp_path, pipeline_config,
):
    """On retry, the input messages include the validation error (single-call fallback)."""
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


# ── Plan-execute-review path (new in Phase 1) ────────────────────────────


def _valid_outline() -> TutorialOutline:  # noqa: F821 — forward ref for pyright
    from src.models import SectionPlan, TutorialOutline

    return TutorialOutline(
        topic="python basics",
        audience="data scientists",
        total_target_seconds=180,
        sections=[
            SectionPlan(id="s1", title="Setup", target_seconds=60, coverage_points=["install"]),
            SectionPlan(
                id="s2", title="Variables", target_seconds=60, coverage_points=["types"],
            ),
            SectionPlan(
                id="s3", title="Functions", target_seconds=60, coverage_points=["def"],
            ),
        ],
        hook=(
            "Let's learn Python together in this hands-on tutorial "
            "covering the fundamentals every data scientist needs!"
        ),
        recap=(
            "We covered the key Python basics today including setup, "
            "variables, and functions that data scientists use daily."
        ),
        cta="Subscribe for more!",
    )


def _valid_section(section_id: str, title: str) -> Section:  # noqa: F821
    from src.models import Section, Shot

    narration = " ".join(
        [
            f"In the {title} section we walk data scientists step by step through the",
            "concepts using the Titanic dataset with clear click-by-click narration",
            "showing VS Code Extensions sidebar and Copilot Chat panel usage with",
            "@task-researcher and @task-planner and @task-implementer one after the",
            "other so viewers can follow along and reproduce the workflow locally",
            "without needing any API keys while we load the data explore it and",
            "build one simple baseline model on the classic Titanic example dataset",
            "which every practising data scientist recognises from their daily work",
            "and the agents generate the code which you simply review then run in",
            "the integrated terminal to watch the printed output appear right away",
        ],
    )
    return Section(
        id=section_id,
        title=title,
        target_seconds=60,
        narration=narration,
        key_points=["key concept"],
        shots=[
            Shot(
                id=f"{section_id}-sh1",
                start_sec=0,
                end_sec=10,
                visual="VS Code editor",
                action="type code",
            ),
        ],
    )


@patch("src.stage_script.OpenAI")
def test_generate_script_plan_execute_path_happy(
    mock_openai_cls, monkeypatch, tmp_path, pipeline_config,
):
    """Plan-execute-review path produces script.json and metadata['path']='plan_execute'."""
    from src.models import Section, TutorialOutline

    mock_openai_cls.return_value = MagicMock()

    outline = _valid_outline()
    sections_by_id = {
        p.id: _valid_section(p.id, p.title) for p in outline.sections
    }

    def fake_typed(client, config, system_prompt, input_messages, provider, response_model,
                   model_override=None):
        if response_model is TutorialOutline:
            return outline
        if response_model is Section:
            # Identify which section is requested via the rendered prompt.
            user_content = input_messages[0]["content"]
            for pid in sections_by_id:
                if f"id: {pid}" in user_content:
                    return sections_by_id[pid]
            return next(iter(sections_by_id.values()))
        raise AssertionError(f"Unexpected response_model {response_model}")

    monkeypatch.setattr("src.stage_script._call_structured_typed", fake_typed)

    out_dir = tmp_path / "01_script"
    result = generate_script("python basics", out_dir, pipeline_config)

    assert result.success is True
    assert result.metadata["path"] == "plan_execute"
    assert (out_dir / "script.json").exists()
    assert result.metadata["sections"] == 3


@patch("src.stage_script.OpenAI")
def test_generate_script_falls_back_on_planner_failure(
    mock_openai_cls, monkeypatch, tmp_path, pipeline_config,
):
    """When the planner raises, fall back to the single-call path and mark metadata."""
    mock_client = MagicMock()
    mock_openai_cls.return_value = mock_client
    mock_client.responses.parse.return_value = _mock_response()

    def boom(*_args, **_kwargs):
        raise RuntimeError("planner offline")

    monkeypatch.setattr("src.stage_script._plan_outline", boom)

    result = generate_script("python basics", tmp_path / "01_script", pipeline_config)

    assert result.success is True
    assert result.metadata["path"] == "single_call_fallback"
    assert Path(result.output_path).exists()


# ── revise_script (Phase 2) ──────────────────────────────────────────────


def _build_sample_script() -> TutorialScript:
    return TutorialScript(**_valid_script_dict())


@patch("src.stage_script._create_client")
def test_revise_script_preserves_unflagged_sections(
    mock_create, monkeypatch, tmp_path, pipeline_config,
):
    """Unflagged sections are identity-preserved; flagged sections get the executor output."""
    from src.models import SectionEdit
    from src.stage_script import revise_script

    mock_create.return_value = MagicMock()
    monkeypatch.setattr("src.stage_script.validate_script", lambda *a, **kw: [])

    script = _build_sample_script()
    sentinel = _valid_section("revised-s2", "Revised Section 2")

    captured: dict[str, object] = {}

    def fake_execute(
        client, config, provider, env, system_prompt,
        outline, plan, audience, source_material, revision_context="",
    ):
        captured["plan_id"] = plan.id
        captured["revision_context"] = revision_context
        return sentinel

    monkeypatch.setattr("src.stage_script._execute_section", fake_execute)

    edits = [SectionEdit(
        section_index=1, issue="too dense", suggested_change="add a beat",
    )]

    result = revise_script(
        script,
        None,
        edits,
        tmp_path / "01_script",
        pipeline_config,
        audience="data scientists",
        source_material="Key findings:\n- foo",
        research_findings=["foo"],
    )

    assert result.success is True
    assert result.metadata["path"] == "revise"
    assert result.metadata["revised_sections"] == 1

    revised = TutorialScript.model_validate_json(Path(result.output_path).read_text())
    # Unflagged sections identity-preserved (byte-identical model dumps).
    assert revised.sections[0].model_dump() == script.sections[0].model_dump()
    assert revised.sections[2].model_dump() == script.sections[2].model_dump()
    # Flagged section replaced with sentinel.
    assert revised.sections[1].id == sentinel.id
    assert revised.sections[1].title == sentinel.title
    # Revision context carried reviewer issue and suggested change.
    ctx = captured["revision_context"]
    assert "too dense" in ctx
    assert "add a beat" in ctx


@patch("src.stage_script._create_client")
def test_revise_script_skips_invalid_index(
    mock_create, monkeypatch, tmp_path, pipeline_config, caplog,
):
    """Out-of-range section indices are skipped with a warning and don't invoke the executor."""
    import logging as _logging

    from src.models import SectionEdit
    from src.stage_script import revise_script

    mock_create.return_value = MagicMock()

    script = _build_sample_script()

    calls: list[str] = []

    def fake_execute(
        client, config, provider, env, system_prompt,
        outline, plan, audience, source_material, revision_context="",
    ):
        calls.append(plan.id)
        return _valid_section(plan.id, plan.title)

    monkeypatch.setattr("src.stage_script._execute_section", fake_execute)
    monkeypatch.setattr("src.stage_script.validate_script", lambda *a, **kw: [])

    edits = [
        SectionEdit(section_index=99, issue="bad", suggested_change="n/a"),
    ]

    with caplog.at_level(_logging.WARNING, logger="src.stage_script"):
        result = revise_script(
            script,
            None,
            edits,
            tmp_path / "01_script",
            pipeline_config,
            audience="data scientists",
            source_material="",
            research_findings=[],
        )

    # Executor was never invoked for the invalid index.
    assert calls == []
    assert result.metadata["revised_sections"] == 0
    assert any("out-of-range index" in rec.message for rec in caplog.records)
