"""Smoke tests for ffmpeg helper functions using real ffmpeg binaries."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from src.ffmpeg_helpers import merge_audio_video, normalize_video, probe_video


def _create_test_video(path: Path, duration: float = 1.0) -> None:
    """Generate a minimal test video using ffmpeg lavfi filters."""
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", f"testsrc=duration={duration}:size=320x240:rate=10",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )


def _create_test_audio(path: Path, duration: float = 1.0) -> None:
    """Generate a minimal test audio file using ffmpeg lavfi filters."""
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}",
            "-c:a", "aac", "-b:a", "64k",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )


@pytest.mark.integration
class TestNormalizeVideoRoundtrip:
    def test_produces_output(self, tmp_path, ffmpeg_available):
        raw = tmp_path / "raw.mp4"
        out = tmp_path / "normalized.mp4"
        _create_test_video(raw, duration=1.0)

        normalize_video(raw, out, {"resolution": "320x240", "fps": 10})

        assert out.exists()
        assert out.stat().st_size > 1000


@pytest.mark.integration
class TestMergeAudioVideo:
    def test_merge_produces_output(self, tmp_path, ffmpeg_available):
        video = tmp_path / "video.mp4"
        audio = tmp_path / "audio.m4a"
        out = tmp_path / "merged.mp4"
        _create_test_video(video, duration=1.0)
        _create_test_audio(audio, duration=1.0)

        merge_audio_video(video, audio, out, {})

        assert out.exists()
        assert out.stat().st_size > 1000


@pytest.mark.integration
class TestProbeVideo:
    def test_returns_streams_and_format(self, tmp_path, ffmpeg_available, ffprobe_available):
        video = tmp_path / "probe_target.mp4"
        _create_test_video(video, duration=1.0)

        info = probe_video(video)

        assert "streams" in info
        assert "format" in info
        assert any(s.get("codec_type") == "video" for s in info["streams"])
