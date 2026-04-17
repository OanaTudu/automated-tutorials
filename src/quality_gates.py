"""Quality gate checks for generated tutorial scripts."""

from __future__ import annotations

import logging
from pathlib import Path

from .ffmpeg_helpers import probe_video
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


def validate_video(
    video_path: Path,
    expected_duration: float,
    config: dict,
) -> list[str]:
    """Return validation errors for a produced video file. Empty list means pass."""
    errors: list[str] = []
    val_cfg = config.get("post", {}).get("validation", {})
    if not val_cfg.get("enabled", True):
        return errors

    if not video_path.exists():
        return [f"Video file does not exist: {video_path}"]

    probe = probe_video(video_path)
    streams = probe.get("streams", [])
    fmt = probe.get("format", {})

    # Find video and audio streams
    video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)

    # Duration check
    actual_duration = float(fmt.get("duration", 0))
    tolerance_pct = val_cfg.get("duration_tolerance_pct", 15) / 100
    if abs(actual_duration - expected_duration) > expected_duration * tolerance_pct:
        errors.append(
            f"Duration {actual_duration:.1f}s outside ±{tolerance_pct * 100:.0f}% "
            f"of expected {expected_duration:.1f}s"
        )

    # Resolution check
    if video_stream:
        expected_res = config.get("post", {}).get("resolution", "1920x1080")
        w, h = expected_res.split("x")
        actual_w = video_stream.get("width", 0)
        actual_h = video_stream.get("height", 0)
        if actual_w != int(w) or actual_h != int(h):
            errors.append(f"Resolution {actual_w}x{actual_h} != expected {expected_res}")
    else:
        errors.append("No video stream found")

    # FPS check
    if video_stream:
        expected_fps = config.get("post", {}).get("fps", 30)
        r_frame_rate = video_stream.get("r_frame_rate", "0/1")
        num, den = r_frame_rate.split("/")
        actual_fps = int(num) / max(int(den), 1)
        if abs(actual_fps - expected_fps) > 1:
            errors.append(f"FPS {actual_fps:.1f} != expected {expected_fps}")

    # Audio stream present
    if not audio_stream:
        errors.append("No audio stream found")

    # A/V sync check
    max_drift = val_cfg.get("max_av_drift_sec", 0.5)
    if video_stream and audio_stream:
        v_dur = float(video_stream.get("duration", fmt.get("duration", 0)))
        a_dur = float(audio_stream.get("duration", fmt.get("duration", 0)))
        drift = abs(v_dur - a_dur)
        if drift > max_drift:
            errors.append(f"A/V drift {drift:.2f}s exceeds {max_drift}s threshold")

    # File size sanity
    min_size_kb = val_cfg.get("min_file_size_kb", 100)
    actual_size_kb = video_path.stat().st_size / 1024
    if actual_size_kb < min_size_kb:
        errors.append(f"File size {actual_size_kb:.0f}KB below minimum {min_size_kb}KB")

    # Codec compliance
    if video_stream and video_stream.get("codec_name") != "h264":
        errors.append(f"Video codec {video_stream.get('codec_name')} != expected h264")
    if audio_stream and audio_stream.get("codec_name") != "aac":
        errors.append(f"Audio codec {audio_stream.get('codec_name')} != expected aac")

    return errors
