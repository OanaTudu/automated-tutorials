"""Tests for stage_tts — mocks Azure SDK and OpenAI client, verifies fallback."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.stage_tts import _dispatch, synthesize_voice

# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture()
def tts_config() -> dict:
    return {
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
            "instructions": "clear tone",
            "response_format": "wav",
        },
    }


# ── dispatch routing ─────────────────────────────────────────────────────


def test_dispatch_unknown_provider_raises(sample_script, tmp_path, tts_config):
    with pytest.raises(ValueError, match="Unknown TTS provider"):
        _dispatch("invalid_provider", sample_script, tmp_path, tts_config)


def test_dispatch_accepts_azure_alias(sample_script, tmp_path, tts_config):
    """Both 'azure_speech' and 'azure' should route to Azure."""
    with patch("src.stage_tts._synthesize_azure", return_value=tmp_path / "voice.wav") as mock_az:
        _dispatch("azure", sample_script, tmp_path, tts_config)
        mock_az.assert_called_once()


def test_dispatch_accepts_openai_alias(sample_script, tmp_path, tts_config):
    """Both 'openai_tts' and 'openai' should route to OpenAI."""
    with patch("src.stage_tts._synthesize_openai", return_value=tmp_path / "voice.wav") as mock_oai:
        _dispatch("openai", sample_script, tmp_path, tts_config)
        mock_oai.assert_called_once()


# ── Primary success ──────────────────────────────────────────────────────


@patch("src.stage_tts._dispatch")
def test_synthesize_voice_primary_success(mock_dispatch, sample_script, tmp_path, pipeline_config):
    mock_dispatch.return_value = tmp_path / "voice.wav"

    result = synthesize_voice(sample_script, tmp_path, pipeline_config)

    assert result.success is True
    assert result.stage == "tts"
    mock_dispatch.assert_called_once_with(
        "azure_speech", sample_script, tmp_path, pipeline_config["tts"]
    )


# ── Fallback on primary failure ──────────────────────────────────────────


@patch("src.stage_tts._dispatch")
def test_synthesize_voice_falls_back(mock_dispatch, sample_script, tmp_path, pipeline_config):
    """When the primary provider raises, the fallback is tried."""
    mock_dispatch.side_effect = [RuntimeError("Azure unavailable"), tmp_path / "voice.wav"]

    result = synthesize_voice(sample_script, tmp_path, pipeline_config)

    assert result.success is True
    assert mock_dispatch.call_count == 2
    fallback_call = mock_dispatch.call_args_list[1]
    assert fallback_call.args[0] == "openai_tts"


# ── Azure synthesizer ───────────────────────────────────────────────────


@patch.dict("os.environ", {"AZURE_SPEECH_KEY": "fake-key", "AZURE_SPEECH_REGION": "eastus"})
@patch("azure.cognitiveservices.speech.SpeechSynthesizer")
@patch("azure.cognitiveservices.speech.audio.AudioOutputConfig")
@patch("azure.cognitiveservices.speech.SpeechConfig")
def test_azure_synthesizer_calls_sdk(
    mock_speech_config, mock_audio_cfg, mock_synth_cls, sample_script, tmp_path, tts_config
):
    from src.stage_tts import _synthesize_azure

    mock_synth = MagicMock()
    mock_synth_cls.return_value = mock_synth

    import azure.cognitiveservices.speech as speechsdk

    mock_result = MagicMock()
    mock_result.reason = speechsdk.ResultReason.SynthesizingAudioCompleted
    mock_synth.speak_ssml_async.return_value.get.return_value = mock_result

    path = _synthesize_azure(sample_script, tmp_path, tts_config["azure"])

    assert path == tmp_path / "voice.wav"
    mock_synth.speak_ssml_async.assert_called_once()


# ── OpenAI synthesizer ──────────────────────────────────────────────────


@patch("openai.OpenAI")
def test_openai_synthesizer_streams_to_file(mock_openai_cls, sample_script, tmp_path, tts_config):
    from src.stage_tts import _synthesize_openai

    mock_client = MagicMock()
    mock_openai_cls.return_value = mock_client

    # Mock the streaming response context manager
    mock_stream_ctx = MagicMock()
    mock_response = MagicMock()
    mock_stream_ctx.__enter__ = MagicMock(return_value=mock_response)
    mock_stream_ctx.__exit__ = MagicMock(return_value=False)
    mock_client.audio.speech.with_streaming_response.create.return_value = mock_stream_ctx

    path = _synthesize_openai(sample_script, tmp_path, tts_config["openai"])

    assert path == tmp_path / "voice.wav"
    # Per-segment path fails without ffmpeg, so fallback writes voice.wav
    mock_response.stream_to_file.assert_any_call(tmp_path / "voice.wav")
