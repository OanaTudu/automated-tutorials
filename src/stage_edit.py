"""Post-production stage: merge screen recording and voice audio into final tutorial."""

from __future__ import annotations

import logging
from pathlib import Path

from .ffmpeg_helpers import burn_captions, merge_audio_video
from .models import StageResult

logger = logging.getLogger(__name__)


def compose_video(
    screen_path: Path,
    voice_path: Path,
    output_dir: Path,
    config: dict,
    srt_path: Path | None = None,
) -> StageResult:
    """Compose final tutorial from screen recording and voice audio.

    Parameters
    ----------
    screen_path:
        Path to the normalised screen recording MP4.
    voice_path:
        Path to the synthesised voice-over audio file.
    output_dir:
        Directory where output artefacts are written.
    config:
        Full pipeline config; the ``post`` key is used for merge settings.
    srt_path:
        Optional SRT caption file to burn into the video.

    Returns
    -------
    StageResult:
        Stage output contract with the path to the final ``tutorial.mp4``.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    post_cfg = config["post"]

    # Merge audio and video
    merged_path = output_dir / "merged.mp4"
    merge_audio_video(screen_path, voice_path, merged_path, post_cfg)

    # Optionally burn captions
    if srt_path and srt_path.exists() and post_cfg.get("captions", {}).get("burn_in", False):
        final_path = output_dir / "tutorial.mp4"
        burn_captions(merged_path, srt_path, final_path)
    else:
        final_path = merged_path

    logger.info("Composed tutorial: %s", final_path)
    return StageResult(stage="edit", success=True, output_path=str(final_path))
