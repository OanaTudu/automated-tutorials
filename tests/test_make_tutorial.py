"""Tests for make_tutorial orchestrator — mocks all stages, verifies chaining."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from src.models import (
    CritiqueResult,
    CritiqueScores,
    ResearchResult,
    StageResult,
    TutorialScript,
)
from src.preflight import PreflightResult

# ── Helpers ──────────────────────────────────────────────────────────────


def _write_config(tmp_path: Path, config: dict) -> Path:
    cfg_path = tmp_path / "config" / "pipeline.yaml"
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(yaml.dump(config), encoding="utf-8")
    return cfg_path


def _valid_script() -> TutorialScript:
    from tests.conftest import _make_section

    return TutorialScript(
        topic="python basics",
        audience="data scientists",
        total_target_seconds=240,
        estimated_words=500,
        hook=(
            "Let's learn Python together in this hands-on tutorial "
            "covering the fundamentals every data scientist needs!"
        ),
        sections=[
            _make_section(id="s1", title="Setup"),
            _make_section(id="s2", title="Variables"),
            _make_section(id="s3", title="Functions"),
        ],
        recap=(
            "We covered the key Python basics today including setup, "
            "variables, and functions that data scientists use daily."
        ),
        cta="Subscribe for more!",
    )


def _setup_research_mock(mock_research, tmp_path: Path) -> None:
    """Write a research.json and configure the mock to return its path."""
    research = ResearchResult(topic="python basics", key_findings=["Python is versatile"])
    research_path = tmp_path / "00_research" / "research.json"
    research_path.parent.mkdir(parents=True, exist_ok=True)
    research_path.write_text(research.model_dump_json(), encoding="utf-8")
    mock_research.return_value = StageResult(
        stage="research", success=True, output_path=str(research_path)
    )


# ── Full pipeline success ────────────────────────────────────────────────


@patch("src.make_tutorial.run_preflight", return_value=PreflightResult())
@patch("src.make_tutorial.critique_tutorial")
@patch("src.make_tutorial.generate_captions")
@patch("src.make_tutorial.compose_video")
@patch("src.make_tutorial.record_demo")
@patch("src.make_tutorial.synthesize_voice")
@patch("src.make_tutorial.validate_video")
@patch("src.make_tutorial.validate_script")
@patch("src.make_tutorial.generate_script")
@patch("src.make_tutorial.research_topic")
def test_make_tutorial_chains_all_stages(
    mock_research,
    mock_gen_script,
    mock_validate,
    mock_validate_video,
    mock_tts,
    mock_record,
    mock_compose,
    mock_captions,
    mock_critique,
    _mock_preflight,
    tmp_path,
    pipeline_config,
):
    from src.make_tutorial import make_tutorial

    # Write config — use tmp_path for output_root to avoid cross-test collisions
    pipeline_config["pipeline"]["output_root"] = str(tmp_path / "outputs")
    cfg_path = _write_config(tmp_path, pipeline_config)

    # Research stage
    _setup_research_mock(mock_research, tmp_path)

    # Script stage returns a script.json
    script = _valid_script()
    script_json_path = tmp_path / "01_script" / "script.json"
    script_json_path.parent.mkdir(parents=True, exist_ok=True)
    script_json_path.write_text(script.model_dump_json(), encoding="utf-8")

    mock_gen_script.return_value = StageResult(
        stage="script", success=True, output_path=str(script_json_path)
    )
    mock_validate.return_value = []  # passes quality gate
    mock_validate_video.return_value = []  # passes video validation
    voice_path = tmp_path / "02_voice" / "voice.wav"
    voice_path.parent.mkdir(parents=True, exist_ok=True)
    voice_path.touch()
    mock_tts.return_value = StageResult(stage="tts", success=True, output_path=str(voice_path))

    # Screen recording
    screen_path = tmp_path / "03_screen" / "screen.mp4"
    screen_path.parent.mkdir(parents=True, exist_ok=True)
    screen_path.touch()
    mock_record.return_value = StageResult(
        stage="record", success=True, output_path=str(screen_path)
    )

    # Captions
    srt_path = tmp_path / "02_voice" / "tutorial.srt"
    srt_path.write_text("1\n00:00:00,000 --> 00:00:05,000\nHello\n\n")
    mock_captions.return_value = srt_path

    # Compose
    rendered_path = tmp_path / "04_render" / "tutorial.mp4"
    rendered_path.parent.mkdir(parents=True, exist_ok=True)
    rendered_path.touch()
    mock_compose.return_value = StageResult(
        stage="edit", success=True, output_path=str(rendered_path)
    )

    # Critique
    critique_path = tmp_path / "critique.json"
    critique_data = CritiqueResult(
        scores=CritiqueScores(
            accuracy=8.0, completeness=8.0, pacing=7.5,
            audience_fit=8.0, teaching_effectiveness=8.0,
        ),
        overall_grade=8.0,
        strengths=["Good coverage"],
        improvements=[],
        summary="Well done",
    )
    critique_path.write_text(critique_data.model_dump_json(), encoding="utf-8")
    mock_critique.return_value = StageResult(
        stage="critique", success=True, output_path=str(critique_path)
    )

    result = make_tutorial("python basics", config_path=cfg_path)

    # Verify all stages called
    mock_research.assert_called_once()
    mock_gen_script.assert_called_once()
    mock_validate.assert_called_once()
    mock_validate_video.assert_called_once()
    mock_tts.assert_called_once()
    mock_record.assert_called_once()
    mock_compose.assert_called_once()
    mock_critique.assert_called_once()

    # Verify result is a Path
    assert isinstance(result, Path)
    assert result.name == "tutorial.mp4"
    assert "05_publish" in str(result)


# ── Quality gate failure ─────────────────────────────────────────────────


@patch("src.make_tutorial.run_preflight", return_value=PreflightResult())
@patch("src.make_tutorial.validate_script")
@patch("src.make_tutorial.generate_script")
@patch("src.make_tutorial.research_topic")
def test_make_tutorial_raises_on_quality_gate_failure(
    mock_research, mock_gen_script, mock_validate, _mock_preflight,
    tmp_path, pipeline_config,
):
    from src.make_tutorial import make_tutorial

    pipeline_config["pipeline"]["output_root"] = str(tmp_path / "outputs")
    cfg_path = _write_config(tmp_path, pipeline_config)

    _setup_research_mock(mock_research, tmp_path)

    script = _valid_script()
    script_json_path = tmp_path / "01_script" / "script.json"
    script_json_path.parent.mkdir(parents=True, exist_ok=True)
    script_json_path.write_text(script.model_dump_json(), encoding="utf-8")

    mock_gen_script.return_value = StageResult(
        stage="script", success=True, output_path=str(script_json_path)
    )
    mock_validate.return_value = ["Duration exceeds cap"]

    with pytest.raises(ValueError, match="quality gate failed"):
        make_tutorial("python basics", config_path=cfg_path)


# ── Output directory structure ───────────────────────────────────────────


@patch("src.make_tutorial.run_preflight", return_value=PreflightResult())
@patch("src.make_tutorial.critique_tutorial")
@patch("src.make_tutorial.generate_captions")
@patch("src.make_tutorial.compose_video")
@patch("src.make_tutorial.record_demo")
@patch("src.make_tutorial.synthesize_voice")
@patch("src.make_tutorial.validate_video")
@patch("src.make_tutorial.validate_script")
@patch("src.make_tutorial.generate_script")
@patch("src.make_tutorial.research_topic")
def test_make_tutorial_creates_dated_slug_directory(
    mock_research,
    mock_gen_script,
    mock_validate,
    mock_validate_video,
    mock_tts,
    mock_record,
    mock_compose,
    mock_captions,
    mock_critique,
    _mock_preflight,
    tmp_path,
    pipeline_config,
):
    from src.make_tutorial import make_tutorial

    pipeline_config["pipeline"]["output_root"] = str(tmp_path / "outputs")
    cfg_path = _write_config(tmp_path, pipeline_config)

    _setup_research_mock(mock_research, tmp_path)

    script = _valid_script()
    script_json_path = tmp_path / "01_script" / "script.json"
    script_json_path.parent.mkdir(parents=True, exist_ok=True)
    script_json_path.write_text(script.model_dump_json(), encoding="utf-8")

    mock_gen_script.return_value = StageResult(
        stage="script", success=True, output_path=str(script_json_path)
    )
    mock_validate.return_value = []
    mock_validate_video.return_value = []
    mock_tts.return_value = StageResult(
        stage="tts", success=True, output_path=str(tmp_path / "voice.wav")
    )
    mock_record.return_value = StageResult(
        stage="record", success=True, output_path=str(tmp_path / "screen.mp4")
    )
    mock_captions.return_value = tmp_path / "tutorial.srt"

    rendered = tmp_path / "04_render" / "tutorial.mp4"
    rendered.parent.mkdir(parents=True, exist_ok=True)
    rendered.touch()
    mock_compose.return_value = StageResult(stage="edit", success=True, output_path=str(rendered))

    critique_path = tmp_path / "critique.json"
    critique_data = CritiqueResult(
        scores=CritiqueScores(
            accuracy=8.0, completeness=8.0, pacing=7.5,
            audience_fit=8.0, teaching_effectiveness=8.0,
        ),
        overall_grade=8.0,
        strengths=["Good coverage"],
        improvements=[],
        summary="Well done",
    )
    critique_path.write_text(critique_data.model_dump_json(), encoding="utf-8")
    mock_critique.return_value = StageResult(
        stage="critique", success=True, output_path=str(critique_path)
    )

    result = make_tutorial("git rebase", config_path=cfg_path)

    # Slug should be lowercase-hyphenated
    assert "git-rebase" in str(result)


# ── Skips captions when engine not configured ────────────────────────────


@patch("src.make_tutorial.run_preflight", return_value=PreflightResult())
@patch("src.make_tutorial.critique_tutorial")
@patch("src.make_tutorial.generate_captions")
@patch("src.make_tutorial.compose_video")
@patch("src.make_tutorial.record_demo")
@patch("src.make_tutorial.synthesize_voice")
@patch("src.make_tutorial.validate_video")
@patch("src.make_tutorial.validate_script")
@patch("src.make_tutorial.generate_script")
@patch("src.make_tutorial.research_topic")
def test_make_tutorial_skips_captions_when_no_engine(
    mock_research,
    mock_gen_script,
    mock_validate,
    mock_validate_video,
    mock_tts,
    mock_record,
    mock_compose,
    mock_captions,
    mock_critique,
    _mock_preflight,
    tmp_path,
    pipeline_config,
):
    from src.make_tutorial import make_tutorial

    pipeline_config["post"]["captions"]["engine"] = ""
    # Use a unique output_root inside tmp_path to avoid rename collisions
    pipeline_config["pipeline"]["output_root"] = str(tmp_path / "out_nocap")
    cfg_path = _write_config(tmp_path, pipeline_config)

    _setup_research_mock(mock_research, tmp_path)

    script = _valid_script()
    script_json_path = tmp_path / "01_script" / "script.json"
    script_json_path.parent.mkdir(parents=True, exist_ok=True)
    script_json_path.write_text(script.model_dump_json(), encoding="utf-8")

    mock_gen_script.return_value = StageResult(
        stage="script", success=True, output_path=str(script_json_path)
    )
    mock_validate.return_value = []
    mock_validate_video.return_value = []
    mock_tts.return_value = StageResult(
        stage="tts", success=True, output_path=str(tmp_path / "voice.wav")
    )
    mock_record.return_value = StageResult(
        stage="record", success=True, output_path=str(tmp_path / "screen.mp4")
    )

    rendered = tmp_path / "04_render_nocap" / "tutorial.mp4"
    rendered.parent.mkdir(parents=True, exist_ok=True)
    rendered.touch()
    mock_compose.return_value = StageResult(stage="edit", success=True, output_path=str(rendered))

    critique_path = tmp_path / "critique.json"
    critique_data = CritiqueResult(
        scores=CritiqueScores(
            accuracy=8.0, completeness=8.0, pacing=7.5,
            audience_fit=8.0, teaching_effectiveness=8.0,
        ),
        overall_grade=8.0,
        strengths=["Good coverage"],
        improvements=[],
        summary="Well done",
    )
    critique_path.write_text(critique_data.model_dump_json(), encoding="utf-8")
    mock_critique.return_value = StageResult(
        stage="critique", success=True, output_path=str(critique_path)
    )

    make_tutorial("python basics", config_path=cfg_path)

    mock_captions.assert_not_called()


# ── Guard: edit_result None when max_retries is negative ─────────────────


@patch("src.make_tutorial.run_preflight", return_value=PreflightResult())
def test_make_tutorial_raises_when_no_video_produced(
    _mock_preflight,
    tmp_path,
    pipeline_config,
):
    from src.make_tutorial import make_tutorial

    # Negative max_retries is now caught by config validation
    pipeline_config["critique"] = {"enabled": True, "max_retries": -1}
    pipeline_config["pipeline"]["output_root"] = str(tmp_path / "outputs")
    cfg_path = _write_config(tmp_path, pipeline_config)

    with pytest.raises(ValueError, match="non-negative integer"):
        make_tutorial("python basics", config_path=cfg_path)


# ── Guard: missing stage output file ─────────────────────────────────────


@patch("src.make_tutorial.run_preflight", return_value=PreflightResult())
@patch("src.make_tutorial.research_topic")
def test_make_tutorial_raises_on_missing_stage_output(
    mock_research,
    _mock_preflight,
    tmp_path,
    pipeline_config,
):
    from src.make_tutorial import make_tutorial

    pipeline_config["pipeline"]["output_root"] = str(tmp_path / "outputs")
    cfg_path = _write_config(tmp_path, pipeline_config)

    # Research returns a StageResult pointing to a non-existent file
    mock_research.return_value = StageResult(
        stage="research", success=True, output_path=str(tmp_path / "ghost.json")
    )

    with pytest.raises(FileNotFoundError, match="Research stage output missing"):
        make_tutorial("python basics", config_path=cfg_path)


# ── Guard: missing required config keys ──────────────────────────────────


@patch("src.make_tutorial.run_preflight", return_value=PreflightResult())
def test_make_tutorial_raises_on_bad_config(
    _mock_preflight,
    tmp_path,
):
    from src.make_tutorial import make_tutorial

    # Write a config missing required keys
    bad_config = {"pipeline": {"output_root": str(tmp_path)}}
    cfg_path = _write_config(tmp_path, bad_config)

    with pytest.raises(ValueError, match="missing required keys"):
        make_tutorial("python basics", config_path=cfg_path)
