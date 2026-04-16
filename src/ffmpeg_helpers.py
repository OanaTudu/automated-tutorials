"""Reusable ffmpeg subprocess wrappers for normalization, merging, and caption burn-in."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def normalize_video(input_path: Path, output_path: Path, cfg: dict) -> None:
    """Normalize any source video to consistent 1080p H.264.

    Parameters
    ----------
    input_path:
        Raw recording to normalise.
    output_path:
        Destination for the normalised MP4.
    cfg:
        Recording config dict; reads *resolution* and *fps* keys.
    """
    resolution: str = cfg.get("resolution", "1920x1080")
    w, h = resolution.split("x")
    fps: int = cfg.get("fps", 30)

    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(input_path),
            "-vf",
            f"scale={w}:{h},fps={fps}",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            str(output_path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    logger.info("Normalized video: %s", output_path)


def merge_audio_video(
    video_path: Path,
    audio_path: Path,
    output_path: Path,
    cfg: dict,
) -> None:
    """Merge screen video with voice audio into a single tutorial file.

    Parameters
    ----------
    video_path:
        Screen-capture video (no audio or scratch audio).
    audio_path:
        Voice-over audio track.
    output_path:
        Destination for the merged MP4.
    cfg:
        Post-production config; reads *crf*, *preset*, *audio_bitrate* keys.
    """
    crf: int = cfg.get("crf", 20)
    preset: str = cfg.get("preset", "medium")
    audio_bitrate: str = cfg.get("audio_bitrate", "192k")

    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(video_path),
            "-i",
            str(audio_path),
            "-map",
            "0:v",
            "-map",
            "1:a",
            "-c:v",
            "libx264",
            "-preset",
            preset,
            "-crf",
            str(crf),
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            audio_bitrate,
            "-movflags",
            "+faststart",
            "-shortest",
            str(output_path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    logger.info("Merged A/V: %s", output_path)


def burn_captions(video_path: Path, srt_path: Path, output_path: Path) -> None:
    """Burn SRT captions into video using the ffmpeg subtitles filter.

    Parameters
    ----------
    video_path:
        Source video file.
    srt_path:
        SRT subtitle file to overlay.
    output_path:
        Destination for the captioned MP4.

    Notes
    -----
    Windows backslashes are escaped for the ffmpeg ``subtitles`` filter which
    uses libass path syntax (forward slashes with colon escaping).
    """
    # Escape Windows path backslashes for ffmpeg subtitle filter
    srt_escaped = str(srt_path).replace("\\", "/").replace(":", "\\\\:")

    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(video_path),
            "-vf",
            f"subtitles={srt_escaped}",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "20",
            "-c:a",
            "copy",
            str(output_path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    logger.info("Burned captions: %s", output_path)
