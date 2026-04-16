"""Caption generation using faster-whisper for local speech-to-text inference."""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def generate_captions(audio_path: Path, output_dir: Path, config: dict) -> Path:
    """Generate SRT captions from audio using faster-whisper.

    Parameters
    ----------
    audio_path:
        Path to the voice-over audio file.
    output_dir:
        Directory where the SRT file is written.
    config:
        Full pipeline config; reads ``post.captions`` for model settings.

    Returns
    -------
    Path:
        Path to the generated ``.srt`` caption file.
    """
    from faster_whisper import WhisperModel

    cap_cfg = config["post"].get("captions", {})
    model = WhisperModel(
        cap_cfg.get("model", "small"),
        device=cap_cfg.get("device", "cpu"),
        compute_type=cap_cfg.get("compute_type", "int8"),
    )

    segments, _info = model.transcribe(str(audio_path), word_timestamps=True, vad_filter=True)

    srt_path = output_dir / "tutorial.srt"
    with srt_path.open("w", encoding="utf-8") as f:
        for i, seg in enumerate(segments, 1):
            start = _format_srt_time(seg.start)
            end = _format_srt_time(seg.end)
            f.write(f"{i}\n{start} --> {end}\n{seg.text.strip()}\n\n")

    logger.info("Generated captions: %s", srt_path)
    return srt_path


def _format_srt_time(seconds: float) -> str:
    """Convert seconds to SRT timestamp format ``HH:MM:SS,mmm``."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"
