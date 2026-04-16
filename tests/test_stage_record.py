"""Tests for stage_record and ffmpeg_helpers — mocks subprocess calls."""

from __future__ import annotations

from unittest.mock import patch

from src.ffmpeg_helpers import burn_captions, merge_audio_video, normalize_video
from src.stage_record import record_demo

# ── stage_record: mode routing ───────────────────────────────────────────


@patch("src.stage_record.normalize_video")
@patch("src.stage_record._record_playwright")
def test_record_demo_playwright_mode(
    mock_playwright, mock_normalize, sample_script, tmp_path, pipeline_config
):
    raw = tmp_path / "raw_playwright.webm"
    raw.touch()
    mock_playwright.return_value = raw

    result = record_demo(sample_script, tmp_path / "03_screen", pipeline_config)

    assert result.success is True
    assert result.stage == "record"
    mock_playwright.assert_called_once()
    mock_normalize.assert_called_once()


@patch("src.stage_record.normalize_video")
@patch("src.stage_record._record_obs")
def test_record_demo_obs_mode(mock_obs, mock_normalize, sample_script, tmp_path, pipeline_config):
    pipeline_config["recording"]["mode"] = "obs"
    raw = tmp_path / "raw_obs.mp4"
    raw.touch()
    mock_obs.return_value = raw

    result = record_demo(sample_script, tmp_path / "03_screen", pipeline_config)

    assert result.success is True
    mock_obs.assert_called_once()


@patch("src.stage_record.normalize_video")
@patch("src.stage_record._record_ffmpeg")
def test_record_demo_ffmpeg_mode(
    mock_ffmpeg, mock_normalize, sample_script, tmp_path, pipeline_config
):
    pipeline_config["recording"]["mode"] = "ffmpeg_gdigrab"
    raw = tmp_path / "raw_ffmpeg.mp4"
    raw.touch()
    mock_ffmpeg.return_value = raw

    result = record_demo(sample_script, tmp_path / "03_screen", pipeline_config)

    assert result.success is True
    mock_ffmpeg.assert_called_once()


def test_record_demo_creates_output_dir(sample_script, tmp_path, pipeline_config):
    out_dir = tmp_path / "nested" / "03_screen"
    with patch("src.stage_record._record_playwright", return_value=out_dir / "raw.webm"):
        with patch("src.stage_record.normalize_video"):
            record_demo(sample_script, out_dir, pipeline_config)
    assert out_dir.exists()


# ── ffmpeg_helpers: normalize_video ──────────────────────────────────────


@patch("src.ffmpeg_helpers.subprocess.run")
def test_normalize_video_calls_ffmpeg(mock_run, tmp_path):
    cfg = {"resolution": "1920x1080", "fps": 30}
    normalize_video(tmp_path / "in.webm", tmp_path / "out.mp4", cfg)

    mock_run.assert_called_once()
    cmd = mock_run.call_args.args[0]
    assert cmd[0] == "ffmpeg"
    assert "scale=1920:1080,fps=30" in cmd


@patch("src.ffmpeg_helpers.subprocess.run")
def test_normalize_video_uses_default_resolution(mock_run, tmp_path):
    normalize_video(tmp_path / "in.webm", tmp_path / "out.mp4", {})

    cmd = mock_run.call_args.args[0]
    assert "scale=1920:1080" in " ".join(cmd)


# ── ffmpeg_helpers: merge_audio_video ────────────────────────────────────


@patch("src.ffmpeg_helpers.subprocess.run")
def test_merge_audio_video_flags(mock_run, tmp_path):
    cfg = {"crf": 20, "preset": "medium", "audio_bitrate": "192k"}
    merge_audio_video(
        tmp_path / "screen.mp4",
        tmp_path / "voice.wav",
        tmp_path / "merged.mp4",
        cfg,
    )

    mock_run.assert_called_once()
    cmd = mock_run.call_args.args[0]
    assert "-movflags" in cmd
    assert "+faststart" in cmd
    assert "-shortest" in cmd


@patch("src.ffmpeg_helpers.subprocess.run")
def test_merge_audio_video_maps_streams(mock_run, tmp_path):
    cfg = {}
    merge_audio_video(
        tmp_path / "screen.mp4",
        tmp_path / "voice.wav",
        tmp_path / "merged.mp4",
        cfg,
    )

    cmd = mock_run.call_args.args[0]
    assert cmd[cmd.index("-map") + 1] == "0:v"
    map_indices = [i for i, x in enumerate(cmd) if x == "-map"]
    assert cmd[map_indices[1] + 1] == "1:a"


# ── ffmpeg_helpers: burn_captions ────────────────────────────────────────


@patch("src.ffmpeg_helpers.subprocess.run")
def test_burn_captions_escapes_windows_path(mock_run, tmp_path):
    srt = tmp_path / "tutorial.srt"
    burn_captions(tmp_path / "merged.mp4", srt, tmp_path / "final.mp4")

    cmd = mock_run.call_args.args[0]
    vf_idx = cmd.index("-vf")
    subtitles_arg = cmd[vf_idx + 1]
    # Should NOT contain backslashes (Windows paths converted to forward)
    assert "\\" not in subtitles_arg or "\\:" in subtitles_arg


@patch("src.ffmpeg_helpers.subprocess.run")
def test_burn_captions_check_true(mock_run, tmp_path):
    srt = tmp_path / "tutorial.srt"
    burn_captions(tmp_path / "merged.mp4", srt, tmp_path / "final.mp4")

    assert mock_run.call_args.kwargs["check"] is True
