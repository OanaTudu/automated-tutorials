"""Fixtures for integration tests that require external tools."""

from __future__ import annotations

import shutil

import pytest


@pytest.fixture()
def ffmpeg_available():
    """Skip the test when ffmpeg is not installed."""
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg not found on PATH")


@pytest.fixture()
def ffprobe_available():
    """Skip the test when ffprobe is not installed."""
    if shutil.which("ffprobe") is None:
        pytest.skip("ffprobe not found on PATH")
