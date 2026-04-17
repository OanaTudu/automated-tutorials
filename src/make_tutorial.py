"""Orchestrator that chains all pipeline stages into a complete tutorial."""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import yaml

from .captions import generate_captions
from .models import CritiqueResult, ResearchResult, TutorialScript
from .preflight import run_preflight
from .quality_gates import validate_script, validate_video
from .stage_critique import critique_tutorial
from .stage_edit import compose_video
from .stage_record import record_demo
from .stage_research import research_topic
from .stage_script import generate_script
from .stage_tts import synthesize_voice

logger = logging.getLogger(__name__)


def _format_research(research: ResearchResult) -> str:
    """Format research results into a text block for the script generation prompt."""
    parts: list[str] = []
    if research.key_findings:
        parts.append("Key findings:")
        parts.extend(f"- {f}" for f in research.key_findings)
    if research.code_examples:
        parts.append("\nCode examples:")
        parts.extend(f"```\n{ex}\n```" for ex in research.code_examples)
    if research.sources:
        parts.append("\nSources:")
        parts.extend(f"- {s}" for s in research.sources)
    if research.raw_notes:
        parts.append(f"\nAdditional notes:\n{research.raw_notes}")
    return "\n".join(parts)


def make_tutorial(
    topic: str,
    config_path: Path | None = None,
    *,
    audience: str = "data scientists",
) -> Path:
    """Produce a complete tutorial video from a topic string.

    Parameters
    ----------
    topic:
        The subject for the tutorial (e.g. ``"git rebase"``).
    config_path:
        Optional path to the pipeline YAML config.  Defaults to
        ``config/pipeline.yaml`` relative to the current working directory.
    audience:
        Target audience for the tutorial (e.g. ``"data scientists"``).

    Returns
    -------
    Path
        Path to the published ``tutorial.mp4`` file.

    Raises
    ------
    ValueError
        When the generated script fails quality-gate validation.
    """
    cfg_path = config_path or Path("config/pipeline.yaml")
    with cfg_path.open(encoding="utf-8") as f:
        config: dict = yaml.safe_load(f)

    config["audience"] = audience

    # Pre-flight environment validation
    preflight = run_preflight(config)
    if preflight.errors:
        raise RuntimeError(f"Preflight failed: {preflight.errors}")
    if preflight.warnings:
        for warning in preflight.warnings:
            logger.warning("Preflight: %s", warning)

    output_root= Path(config["pipeline"]["output_root"])
    slug = topic.lower().replace(" ", "-")
    run_dir = output_root / f"{date.today().isoformat()}-{slug}"

    # Stage 0: Research
    logger.info("Stage 0: Researching '%s'", topic)
    research_result = research_topic(topic, run_dir / "00_research", config, audience=audience)
    research = ResearchResult.model_validate_json(
        Path(research_result.output_path).read_text(encoding="utf-8"),
    )
    config["source_material"] = _format_research(research)

    # Critique retry configuration
    critique_cfg = config.get("critique", {})
    critique_enabled = critique_cfg.get("enabled", True)
    max_retries = critique_cfg.get("max_retries", 2) if critique_enabled else 0
    min_grade = critique_cfg.get("min_overall_grade", 7.0)
    min_category = critique_cfg.get("min_category_score", 4.0)

    prev_grade = 0.0
    edit_result = None

    for attempt in range(max_retries + 1):
        # Stage 1: Script generation
        logger.info("Stage 1: Generating script for '%s' (attempt %d)", topic, attempt + 1)
        script_result = generate_script(topic, run_dir / "01_script", config)
        script = TutorialScript.model_validate_json(
            Path(script_result.output_path).read_text(encoding="utf-8"),
        )

        # Quality gate
        errors = validate_script(
            script,
            max_seconds=config["pipeline"]["max_duration_seconds"],
            audience=audience,
        )
        if errors:
            raise ValueError(f"Script quality gate failed: {errors}")

        # Stage 2: Voice synthesis
        logger.info("Stage 2: Synthesizing voice")
        voice_result = synthesize_voice(script, run_dir / "02_voice", config)

        # Stage 3: Screen recording
        logger.info("Stage 3: Recording screen demo")
        screen_result = record_demo(script, run_dir / "03_screen", config)

        # Stage 4: Captions (optional)
        srt_path: Path | None = None
        if config["post"].get("captions", {}).get("engine"):
            logger.info("Stage 4a: Generating captions")
            srt_path = generate_captions(
                Path(voice_result.output_path),
                run_dir / "02_voice",
                config,
            )

        # Stage 5: Post-production
        logger.info("Stage 5: Composing final video")
        edit_result = compose_video(
            Path(screen_result.output_path),
            Path(voice_result.output_path),
            run_dir / "04_render",
            config,
            srt_path=srt_path,
        )

        # Video validation
        video_errors = validate_video(
            Path(edit_result.output_path),
            script.total_target_seconds,
            config,
        )
        if video_errors:
            raise ValueError(f"Video quality gate failed: {video_errors}")

        # Critique (if enabled)
        if not critique_enabled:
            break

        logger.info("Stage 6: Critiquing tutorial (attempt %d)", attempt + 1)
        critique_stage_result = critique_tutorial(
            script, research, run_dir / "06_critique", config, audience=audience,
        )
        critique_result = CritiqueResult.model_validate_json(
            Path(critique_stage_result.output_path).read_text(encoding="utf-8"),
        )

        # Check if critique passes
        scores_pass = all(
            v >= min_category
            for v in critique_result.scores.model_dump().values()
        )
        if critique_result.overall_grade >= min_grade and scores_pass:
            logger.info("Critique passed: grade=%.1f", critique_result.overall_grade)
            break

        # Divergence detection: stop if grade not improving
        if attempt > 0 and critique_result.overall_grade <= prev_grade:
            logger.warning(
                "Grade not improving (%.1f -> %.1f), stopping retries",
                prev_grade, critique_result.overall_grade,
            )
            break

        prev_grade = critique_result.overall_grade

        if attempt < max_retries:
            logger.warning(
                "Critique attempt %d: grade=%.1f, retrying",
                attempt + 1, critique_result.overall_grade,
            )
            config["revision_feedback"] = "\n".join(critique_result.improvements)
        else:
            logger.warning("Critique max retries reached, proceeding with best attempt")

    # Publish (after critique loop)
    publish_dir = run_dir / "05_publish"
    publish_dir.mkdir(parents=True, exist_ok=True)
    final_path = publish_dir / "tutorial.mp4"
    Path(edit_result.output_path).replace(final_path)

    logger.info("Tutorial published: %s", final_path)

    return final_path
