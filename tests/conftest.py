"""Shared test fixtures for the tutorial pipeline test suite."""

from __future__ import annotations

import pytest

from src.models import Section, Shot, StageResult, TutorialScript


def _make_shot(
    id: str = "s1-shot1",
    start: float = 0.0,
    end: float = 10.0,
) -> Shot:
    return Shot(
        id=id,
        start_sec=start,
        end_sec=end,
        visual="VS Code editor",
        action="Type code in terminal",
    )


def _make_section(
    id: str = "s1",
    title: str = "Introduction",
    target_seconds: int = 60,
    narration: str = (
        "Welcome to this tutorial on Python basics where we will cover the essential concepts "
        "that every data scientist needs to know for effective programming and analysis workflows."
    ),
    n_shots: int = 1,
) -> Section:
    shots = [_make_shot(id=f"{id}-shot{i}", start=i * 10, end=(i + 1) * 10) for i in range(n_shots)]
    return Section(
        id=id,
        title=title,
        target_seconds=target_seconds,
        narration=narration,
        key_points=["point one", "point two"],
        shots=shots,
    )


@pytest.fixture()
def sample_script() -> TutorialScript:
    """A valid TutorialScript that passes all quality gates at 300s / ~500 words."""
    return TutorialScript(
        topic="python basics",
        audience="data scientists",
        total_target_seconds=240,
        estimated_words=500,
        hook=(
            "Let's learn Python together in this hands-on tutorial "
            "that covers the fundamentals every data scientist needs!"
        ),
        sections=[
            _make_section(id="s1", title="Setup", target_seconds=60, n_shots=2),
            _make_section(id="s2", title="Variables", target_seconds=60, n_shots=2),
            _make_section(id="s3", title="Functions", target_seconds=60, n_shots=2),
        ],
        recap=(
            "We covered the key Python basics today including setup, "
            "variables, and functions that every data scientist should master."
        ),
        cta="Subscribe for more data science tutorials and hit the notification bell!",
    )


@pytest.fixture()
def pipeline_config() -> dict:
    """Minimal pipeline config dict matching pipeline.yaml structure."""
    return {
        "pipeline": {
            "max_duration_seconds": 300,
            "output_root": "outputs",
            "log_level": "INFO",
        },
        "audience": "beginner developers",
        "source_material": "",
        "script": {
            "provider": "openai",
            "model": "gpt-4.1",
            "max_output_tokens": 2200,
            "temperature": 0.4,
        },
        "tts": {
            "primary": "azure_speech",
            "fallback": "openai_tts",
            "azure": {
                "voice": "en-US-AvaMultilingualNeural",
                "style": "narration-professional",
                "style_degree": "1.1",
                "speaking_rate": "-5%",
                "output_format": "riff-24khz-16bit-mono-pcm",
            },
            "openai": {
                "model": "gpt-4o-mini-tts",
                "voice": "marin",
                "instructions": "tutorial tone",
                "response_format": "wav",
            },
        },
        "recording": {
            "mode": "playwright",
            "resolution": "1920x1080",
            "fps": 30,
        },
        "post": {
            "engine": "ffmpeg",
            "crf": 20,
            "preset": "medium",
            "audio_bitrate": "192k",
            "captions": {
                "engine": "faster_whisper",
                "model": "small",
                "device": "cpu",
                "compute_type": "int8",
                "burn_in": True,
            },
        },
    }


@pytest.fixture()
def make_stage_result():
    """Factory fixture for creating StageResult objects."""

    def _factory(
        stage: str = "test",
        success: bool = True,
        output_path: str = "output.mp4",
    ) -> StageResult:
        return StageResult(stage=stage, success=success, output_path=output_path)

    return _factory
