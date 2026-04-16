"""Tests for stage_edit.compose_video and captions.generate_captions / _format_srt_time."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.captions import _format_srt_time
from src.stage_edit import compose_video

# ══════════════════════════════════════════════════════════════════════════
# stage_edit.compose_video
# ══════════════════════════════════════════════════════════════════════════


@patch("src.stage_edit.burn_captions")
@patch("src.stage_edit.merge_audio_video")
def test_compose_video_merges_without_captions(mock_merge, mock_burn, tmp_path, pipeline_config):
    """Without SRT, only merge is called, not burn."""
    result = compose_video(
        tmp_path / "screen.mp4",
        tmp_path / "voice.wav",
        tmp_path / "04_render",
        pipeline_config,
        srt_path=None,
    )

    assert result.success is True
    assert result.stage == "edit"
    mock_merge.assert_called_once()
    mock_burn.assert_not_called()


@patch("src.stage_edit.burn_captions")
@patch("src.stage_edit.merge_audio_video")
def test_compose_video_burns_captions_when_present(
    mock_merge, mock_burn, tmp_path, pipeline_config
):
    srt = tmp_path / "tutorial.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:05,000\nHello\n\n")

    result = compose_video(
        tmp_path / "screen.mp4",
        tmp_path / "voice.wav",
        tmp_path / "04_render",
        pipeline_config,
        srt_path=srt,
    )

    assert result.success is True
    mock_merge.assert_called_once()
    mock_burn.assert_called_once()


@patch("src.stage_edit.burn_captions")
@patch("src.stage_edit.merge_audio_video")
def test_compose_video_skips_burn_when_burn_in_disabled(
    mock_merge, mock_burn, tmp_path, pipeline_config
):
    pipeline_config["post"]["captions"]["burn_in"] = False
    srt = tmp_path / "tutorial.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:05,000\nHello\n\n")

    compose_video(
        tmp_path / "screen.mp4",
        tmp_path / "voice.wav",
        tmp_path / "04_render",
        pipeline_config,
        srt_path=srt,
    )

    mock_burn.assert_not_called()


@patch("src.stage_edit.burn_captions")
@patch("src.stage_edit.merge_audio_video")
def test_compose_video_creates_output_dir(mock_merge, mock_burn, tmp_path, pipeline_config):
    out_dir = tmp_path / "nested" / "04_render"
    compose_video(
        tmp_path / "screen.mp4",
        tmp_path / "voice.wav",
        out_dir,
        pipeline_config,
    )
    assert out_dir.exists()


# ══════════════════════════════════════════════════════════════════════════
# captions._format_srt_time
# ══════════════════════════════════════════════════════════════════════════


def test_format_srt_time_zero():
    assert _format_srt_time(0.0) == "00:00:00,000"


def test_format_srt_time_simple():
    assert _format_srt_time(5.5) == "00:00:05,500"


def test_format_srt_time_minutes():
    assert _format_srt_time(65.123) == "00:01:05,123"


def test_format_srt_time_hours():
    assert _format_srt_time(3661.5) == "01:01:01,500"


def test_format_srt_time_millisecond_precision():
    result = _format_srt_time(1.999)
    assert result == "00:00:01,999"


# ══════════════════════════════════════════════════════════════════════════
# captions.generate_captions (mocked faster-whisper)
# ══════════════════════════════════════════════════════════════════════════


@patch("faster_whisper.WhisperModel")
def test_generate_captions_writes_srt(mock_model_cls, tmp_path, pipeline_config):
    from src.captions import generate_captions

    # Mock model and segments
    mock_model = MagicMock()
    mock_model_cls.return_value = mock_model

    seg1 = MagicMock()
    seg1.start = 0.0
    seg1.end = 3.5
    seg1.text = " Hello world "

    seg2 = MagicMock()
    seg2.start = 3.5
    seg2.end = 7.0
    seg2.text = " Welcome to the tutorial "

    mock_model.transcribe.return_value = ([seg1, seg2], MagicMock())

    audio_path = tmp_path / "voice.wav"
    audio_path.touch()

    srt_path = generate_captions(audio_path, tmp_path, pipeline_config)

    assert srt_path.exists()
    content = srt_path.read_text()
    assert "Hello world" in content
    assert "00:00:00,000 --> 00:00:03,500" in content
    assert "00:00:03,500 --> 00:00:07,000" in content
