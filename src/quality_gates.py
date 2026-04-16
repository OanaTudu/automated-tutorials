"""Quality gate checks for generated tutorial scripts."""

from __future__ import annotations

import logging

from .models import TutorialScript

logger = logging.getLogger(__name__)

WORDS_PER_MINUTE_MIN = 125
WORDS_PER_MINUTE_MAX = 145


def validate_script(
    script: TutorialScript,
    *,
    max_seconds: int = 300,
    audience: str = "",
) -> list[str]:
    """Return validation errors for a tutorial script. Empty list means pass."""
    errors: list[str] = []

    # --- Duration cap -----------------------------------------------------
    if script.total_target_seconds > max_seconds:
        errors.append(f"Duration {script.total_target_seconds}s exceeds {max_seconds}s cap")

    # --- Pacing range -----------------------------------------------------
    duration_min = script.estimated_words / WORDS_PER_MINUTE_MAX * 60
    duration_max = script.estimated_words / WORDS_PER_MINUTE_MIN * 60

    if duration_max < script.total_target_seconds * 0.7:
        errors.append("Script too sparse for target duration")
    if duration_min > script.total_target_seconds * 1.1:
        errors.append("Script too dense for target duration")

    # --- Section count ----------------------------------------------------
    section_count = len(script.sections)
    if not (3 <= section_count <= 5):
        errors.append(f"Expected 3-5 sections, got {section_count}")

    # --- Shot timing continuity -------------------------------------------
    for section in script.sections:
        for shot in section.shots:
            if shot.end_sec <= shot.start_sec:
                errors.append(f"Shot {shot.id} has invalid timing")

    # --- Content safety: flag unverified claims ---------------------------
    for section in script.sections:
        if "needs_verification" in section.narration.lower():
            errors.append(f"Section '{section.title}' contains unverified claims")

    # --- Narration substance ----------------------------------------------
    for section in script.sections:
        word_count = len(section.narration.split())
        if word_count < 20:
            errors.append(
                f"Section '{section.title}' narration too thin "
                f"({word_count} words, min 20)"
            )

    # --- Key points present -----------------------------------------------
    for section in script.sections:
        if not section.key_points:
            errors.append(f"Section '{section.title}' has no key_points")

    # --- Minimum shot duration --------------------------------------------
    for section in script.sections:
        for shot in section.shots:
            duration = shot.end_sec - shot.start_sec
            if 0 < duration < 2:
                errors.append(f"Shot {shot.id} is only {duration:.1f}s (min 2s)")

    # --- Section sum vs total consistency ---------------------------------
    section_sum = sum(s.target_seconds for s in script.sections)
    if script.total_target_seconds > 0:
        ratio = section_sum / script.total_target_seconds
        if not (0.75 <= ratio <= 1.25):
            errors.append(
                f"Section target_seconds sum ({section_sum}s) differs from "
                f"total ({script.total_target_seconds}s) by more than 25%"
            )

    # --- Hook/recap non-trivial -------------------------------------------
    if len(script.hook.split()) < 10:
        errors.append(f"Hook too short ({len(script.hook.split())} words, min 10)")
    if len(script.recap.split()) < 10:
        errors.append(f"Recap too short ({len(script.recap.split())} words, min 10)")

    # --- Audience mention -------------------------------------------------
    if audience:
        audience_words = set(audience.lower().split())
        all_narration = " ".join(s.narration.lower() for s in script.sections)
        if not any(word in all_narration for word in audience_words):
            errors.append(f"No section narration references the target audience: '{audience}'")

    if errors:
        logger.warning("Script validation found %d issue(s)", len(errors))
    else:
        logger.info("Script passed all quality gates")

    return errors
