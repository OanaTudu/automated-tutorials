"""Orchestrator that chains all pipeline stages into a complete tutorial."""

from __future__ import annotations

import json
import logging
import time
from datetime import date
from pathlib import Path

import yaml

from .captions import generate_captions
from .models import CritiqueResult, ResearchResult, StageResult, TutorialScript
from .preflight import run_preflight
from .quality_gates import validate_script, validate_video
from .stage_critique import critique_tutorial
from .stage_edit import compose_video
from .stage_record import record_demo
from .stage_research import research_topic
from .stage_script import generate_script, revise_script
from .stage_tts import synthesize_voice

logger = logging.getLogger(__name__)


def _read_stage_output(stage_result: StageResult, stage_name: str) -> str:
    """Read and return stage output JSON, raising a clear error if the file is missing."""
    path = Path(stage_result.output_path)
    if not path.exists():
        raise FileNotFoundError(
            f"{stage_name} stage output missing: {path}. "
            f"The stage reported success={stage_result.success} but produced no file."
        )
    return path.read_text(encoding="utf-8")


_REQUIRED_CONFIG_KEYS = [
    ("pipeline", "output_root"),
    ("pipeline", "max_duration_seconds"),
    ("script", "provider"),
    ("script", "model"),
    ("script", "max_output_tokens"),
    ("tts", "primary"),
    ("tts", "fallback"),
    ("recording", "mode"),
    ("post", "engine"),
]


def _validate_config(config: dict) -> None:
    """Raise ValueError listing all missing required config keys."""
    missing: list[str] = []
    for section, key in _REQUIRED_CONFIG_KEYS:
        if not isinstance(config.get(section), dict) or key not in config[section]:
            missing.append(f"{section}.{key}")
    if missing:
        raise ValueError(f"Pipeline config missing required keys: {', '.join(missing)}")

    # Semantic checks
    errors: list[str] = []
    max_dur = config.get("pipeline", {}).get("max_duration_seconds")
    if isinstance(max_dur, (int, float)) and max_dur <= 0:
        errors.append("pipeline.max_duration_seconds must be > 0")

    max_retries = config.get("critique", {}).get("max_retries")
    if max_retries is not None and (not isinstance(max_retries, int) or max_retries < 0):
        errors.append("critique.max_retries must be a non-negative integer")

    if errors:
        raise ValueError(f"Pipeline config invalid: {'; '.join(errors)}")


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


def _write_run_report(
    run_dir: Path,
    topic: str,
    audience: str,
    stage_results: list[StageResult],
    final_video: Path | None,
    warnings: list[str],
    critique: CritiqueResult | None = None,
) -> Path:
    """Write a human-readable run report. Never raises — failures are logged and swallowed."""
    report_path = run_dir / "run_report.md"
    try:
        lines: list[str] = [f"# Run Report — {topic}", ""]

        # Run Metadata
        total_duration = 0.0
        for sr in stage_results:
            dur = sr.metadata.get("duration_sec", 0) if isinstance(sr.metadata, dict) else 0
            if isinstance(dur, (int, float)):
                total_duration += float(dur)

        lines.append("## Run Metadata")
        lines.append("")
        lines.append(f"- Date: {date.today().isoformat()}")
        lines.append(f"- Audience: {audience}")
        lines.append(
            f"- Final video: {final_video if final_video is not None else '(not produced)'}",
        )
        lines.append(f"- Total duration (s): {round(total_duration, 2)}")
        lines.append(f"- Total stages run: {len(stage_results)}")
        lines.append("")

        # Stages
        lines.append("## Stages")
        lines.append("")
        lines.append("| Stage | Status | Output | Duration (s) | Metadata |")
        lines.append("| --- | --- | --- | --- | --- |")
        for sr in stage_results:
            stage = getattr(sr, "stage", "?")
            success = getattr(sr, "success", False)
            status = "✅" if success else "❌"
            output = getattr(sr, "output_path", "") or "-"
            meta = sr.metadata if isinstance(sr.metadata, dict) else {}
            dur = meta.get("duration_sec", "-")
            if isinstance(dur, (int, float)):
                dur_str = f"{round(float(dur), 2)}"
            else:
                dur_str = str(dur)
            extra_items = [
                f"{k}={v}" for k, v in meta.items() if k != "duration_sec"
            ]
            extra = ", ".join(extra_items) if extra_items else "-"
            lines.append(f"| {stage} | {status} | {output} | {dur_str} | {extra} |")
        lines.append("")

        # Critique
        if critique is not None:
            lines.append("## Critique")
            lines.append("")
            overall = getattr(critique, "overall_grade", "-")
            lines.append(f"- Overall grade: {overall}")
            lines.append("")
            scores = getattr(critique, "scores", None)
            if scores is not None:
                lines.append("| Category | Score |")
                lines.append("| --- | --- |")
                try:
                    score_dict = scores.model_dump()
                except Exception:  # noqa: BLE001
                    score_dict = {}
                for name, val in score_dict.items():
                    lines.append(f"| {name} | {val} |")
                lines.append("")

            strengths = list(getattr(critique, "strengths", []) or [])[:5]
            if strengths:
                lines.append("### Strengths")
                lines.append("")
                lines.extend(f"- {s}" for s in strengths)
                lines.append("")

            improvements = list(getattr(critique, "improvements", []) or [])[:5]
            if improvements:
                lines.append("### Improvements")
                lines.append("")
                lines.extend(f"- {s}" for s in improvements)
                lines.append("")

            section_edits = list(getattr(critique, "section_edits", []) or [])
            if section_edits:
                lines.append(f"- Section edits: {len(section_edits)}")
                lines.append("")

        # Warnings
        lines.append("## Warnings")
        lines.append("")
        if warnings:
            lines.extend(f"- {w}" for w in warnings)
        else:
            lines.append("(none)")
        lines.append("")

        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text("\n".join(lines), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to write run report at %s: %s", report_path, exc)
    return report_path


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

    _validate_config(config)
    config["audience"] = audience

    warnings: list[str] = []

    # Pre-flight environment validation
    preflight = run_preflight(config)
    if preflight.errors:
        raise RuntimeError(f"Preflight failed: {preflight.errors}")
    if preflight.warnings:
        for warning in preflight.warnings:
            logger.warning("Preflight: %s", warning)
            warnings.append(f"Preflight: {warning}")

    output_root= Path(config["pipeline"]["output_root"])
    slug = topic.lower().replace(" ", "-")
    run_dir = output_root / f"{date.today().isoformat()}-{slug}"

    stage_results: list[StageResult] = []
    last_critique_result: CritiqueResult | None = None

    def _timed(stage_name: str, fn, *args, **kwargs) -> StageResult:  # noqa: ARG001
        start = time.perf_counter()
        try:
            result = fn(*args, **kwargs)
        finally:
            elapsed = round(time.perf_counter() - start, 2)
        if isinstance(result, StageResult):
            result.metadata["duration_sec"] = elapsed
        return result

    try:
        # Stage 0: Research
        logger.info("Stage 0: Researching '%s'", topic)
        research_result = _timed(
            "research",
            research_topic,
            topic,
            run_dir / "00_research",
            config,
            audience=audience,
        )
        stage_results.append(research_result)
        research = ResearchResult.model_validate_json(
            _read_stage_output(research_result, "Research"),
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
        # When True, the next iteration reuses the script.json produced by a prior
        # targeted revision instead of regenerating — and skips stages 2-5 since
        # those were already re-run against the revised script in the prior iter.
        skip_regen_and_stages = False

        for attempt in range(max_retries + 1):
            if skip_regen_and_stages:
                # Reload the revised script and jump straight to critique.
                skip_regen_and_stages = False
                script = TutorialScript.model_validate_json(
                    (run_dir / "01_script" / "script.json").read_text(encoding="utf-8"),
                )
            else:
                # Stage 1: Script generation
                logger.info("Stage 1: Generating script for '%s' (attempt %d)", topic, attempt + 1)
                script_result = _timed(
                    "script", generate_script, topic, run_dir / "01_script", config,
                )
                stage_results.append(script_result)
                script = TutorialScript.model_validate_json(
                    _read_stage_output(script_result, "Script"),
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
                voice_result = _timed(
                    "voice", synthesize_voice, script, run_dir / "02_voice", config,
                )
                stage_results.append(voice_result)

                # Stage 3: Screen recording
                logger.info("Stage 3: Recording screen demo")
                screen_result = _timed(
                    "record", record_demo, script, run_dir / "03_screen", config,
                )
                stage_results.append(screen_result)

                # Stage 4: Captions (optional)
                srt_path: Path | None = None
                if config["post"].get("captions", {}).get("engine"):
                    logger.info("Stage 4a: Generating captions")
                    cap_start = time.perf_counter()
                    srt_path = generate_captions(
                        Path(voice_result.output_path),
                        run_dir / "02_voice",
                        config,
                    )
                    cap_elapsed = round(time.perf_counter() - cap_start, 2)
                    stage_results.append(
                        StageResult(
                            stage="captions",
                            success=True,
                            output_path=str(srt_path),
                            metadata={"duration_sec": cap_elapsed},
                        ),
                    )

                # Stage 5: Post-production
                logger.info("Stage 5: Composing final video")
                edit_result = _timed(
                    "compose",
                    compose_video,
                    Path(screen_result.output_path),
                    Path(voice_result.output_path),
                    run_dir / "04_render",
                    config,
                    srt_path=srt_path,
                )
                stage_results.append(edit_result)

                # Video validation — use actual TTS duration (from manifest) rather than
                # the script's target, since TTS speed varies from the LLM's estimate.
                manifest_path = run_dir / "02_voice" / "timing_manifest.json"
                actual_target_sec = script.total_target_seconds
                try:
                    if manifest_path.exists():
                        _manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                        manifest_ms = _manifest.get("total_duration_ms", 0)
                        if isinstance(manifest_ms, (int, float)) and manifest_ms > 0:
                            actual_target_sec = manifest_ms / 1000.0
                except (json.JSONDecodeError, ValueError):
                    logger.warning("Could not read timing manifest, using script estimate")
                    warnings.append("Could not read timing manifest, using script estimate")

                video_errors = validate_video(
                    Path(edit_result.output_path),
                    actual_target_sec,
                    config,
                )
                if video_errors:
                    raise ValueError(f"Video quality gate failed: {video_errors}")

            # Critique (if enabled)
            if not critique_enabled:
                break

            logger.info("Stage 6: Critiquing tutorial (attempt %d)", attempt + 1)
            critique_stage_result = _timed(
                "critique",
                critique_tutorial,
                script,
                research,
                run_dir / "06_critique",
                config,
                audience=audience,
            )
            stage_results.append(critique_stage_result)
            critique_result = CritiqueResult.model_validate_json(
                _read_stage_output(critique_stage_result, "Critique"),
            )
            last_critique_result = critique_result

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
                msg = (
                    f"Grade not improving ({prev_grade:.1f} -> "
                    f"{critique_result.overall_grade:.1f}), stopping retries"
                )
                logger.warning(msg)
                warnings.append(msg)
                break

            prev_grade = critique_result.overall_grade

            if attempt < max_retries:
                # Prefer targeted revision when the critique provided valid section_edits.
                section_edits = critique_result.section_edits
                valid_edits = bool(section_edits) and all(
                    0 <= e.section_index < len(script.sections) for e in section_edits
                )
                if valid_edits:
                    try:
                        logger.info(
                            "Critique attempt %d: applying %d targeted section edit(s)",
                            attempt + 1, len(section_edits),
                        )
                        revise_result = _timed(
                            "revise",
                            revise_script,
                            script,
                            None,
                            section_edits,
                            run_dir / "01_script",
                            config,
                            audience,
                            config.get("source_material", ""),
                            research.key_findings,
                        )
                        if isinstance(revise_result, StageResult):
                            stage_results.append(revise_result)
                        revised_script = TutorialScript.model_validate_json(
                            (run_dir / "01_script" / "script.json").read_text(encoding="utf-8"),
                        )

                        # Re-run stages 2-5 against the revised script.
                        logger.info("Stage 2: Re-synthesizing voice (post-revision)")
                        voice_result = _timed(
                            "voice",
                            synthesize_voice,
                            revised_script,
                            run_dir / "02_voice",
                            config,
                        )
                        stage_results.append(voice_result)
                        logger.info("Stage 3: Re-recording screen demo (post-revision)")
                        screen_result = _timed(
                            "record",
                            record_demo,
                            revised_script,
                            run_dir / "03_screen",
                            config,
                        )
                        stage_results.append(screen_result)
                        srt_path = None
                        if config["post"].get("captions", {}).get("engine"):
                            logger.info("Stage 4a: Regenerating captions (post-revision)")
                            cap_start = time.perf_counter()
                            srt_path = generate_captions(
                                Path(voice_result.output_path),
                                run_dir / "02_voice",
                                config,
                            )
                            cap_elapsed = round(time.perf_counter() - cap_start, 2)
                            stage_results.append(
                                StageResult(
                                    stage="captions",
                                    success=True,
                                    output_path=str(srt_path),
                                    metadata={"duration_sec": cap_elapsed},
                                ),
                            )
                        logger.info("Stage 5: Re-composing final video (post-revision)")
                        edit_result = _timed(
                            "compose",
                            compose_video,
                            Path(screen_result.output_path),
                            Path(voice_result.output_path),
                            run_dir / "04_render",
                            config,
                            srt_path=srt_path,
                        )
                        stage_results.append(edit_result)

                        config.pop("revision_feedback", None)
                        skip_regen_and_stages = True
                        continue
                    except Exception as exc:  # noqa: BLE001 — fall through to full regen
                        msg = (
                            f"Targeted revision failed ({exc}); "
                            "falling back to full regeneration"
                        )
                        logger.warning(msg)
                        warnings.append(msg)

                logger.warning(
                    "Critique attempt %d: grade=%.1f, retrying",
                    attempt + 1, critique_result.overall_grade,
                )
                warnings.append(
                    f"Critique attempt {attempt + 1}: "
                    f"grade={critique_result.overall_grade:.1f}, retrying",
                )
                config["revision_feedback"] = "\n".join(critique_result.improvements)
            else:
                logger.warning("Critique max retries reached, proceeding with best attempt")
                warnings.append("Critique max retries reached, proceeding with best attempt")

        # Publish (after critique loop)
        if edit_result is None:
            raise RuntimeError("Pipeline produced no video — check stage logs for errors")

        publish_dir = run_dir / "05_publish"
        publish_dir.mkdir(parents=True, exist_ok=True)
        final_path = publish_dir / "tutorial.mp4"
        Path(edit_result.output_path).replace(final_path)

        logger.info("Tutorial published: %s", final_path)

        _write_run_report(
            run_dir,
            topic,
            audience,
            stage_results,
            final_path,
            warnings,
            critique=last_critique_result,
        )

        return final_path
    except Exception as exc:
        warnings.append(f"Pipeline error: {exc}")
        _write_run_report(
            run_dir,
            topic,
            audience,
            stage_results,
            None,
            warnings,
            critique=last_critique_result,
        )
        raise
