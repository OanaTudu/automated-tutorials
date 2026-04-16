"""Voice synthesis stage with Azure AI Speech primary and OpenAI TTS fallback."""

from __future__ import annotations

import logging
from pathlib import Path

from .models import StageResult, TutorialScript
from .ssml_builder import build_ssml

logger = logging.getLogger(__name__)


def synthesize_voice(script: TutorialScript, output_dir: Path, config: dict) -> StageResult:
    """Synthesize tutorial narration from script sections.

    Uses the primary TTS provider from config, falling back to the
    secondary provider on failure.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    tts_cfg = config["tts"]
    primary = tts_cfg["primary"]
    fallback = tts_cfg["fallback"]

    try:
        output_path = _dispatch(primary, script, output_dir, tts_cfg)
    except Exception:
        logger.warning("Primary TTS (%s) failed, falling back to %s", primary, fallback)
        output_path = _dispatch(fallback, script, output_dir, tts_cfg)

    return StageResult(stage="tts", success=True, output_path=str(output_path))


def _dispatch(provider: str, script: TutorialScript, output_dir: Path, tts_cfg: dict) -> Path:
    """Route to the correct provider implementation."""
    if provider in ("azure_speech", "azure"):
        return _synthesize_azure(script, output_dir, tts_cfg["azure"])
    if provider in ("openai_tts", "openai"):
        return _synthesize_openai(script, output_dir, tts_cfg["openai"])
    msg = f"Unknown TTS provider: {provider}"
    raise ValueError(msg)


def _synthesize_azure(script: TutorialScript, output_dir: Path, cfg: dict) -> Path:
    """Synthesize narration via Azure AI Speech SDK with SSML."""
    import os

    import azure.cognitiveservices.speech as speechsdk

    region = os.environ["AZURE_SPEECH_REGION"]
    speech_key = os.environ.get("AZURE_SPEECH_KEY")

    if speech_key:
        speech_config = speechsdk.SpeechConfig(
            subscription=speech_key,
            region=region,
        )
    else:
        from azure.identity import DefaultAzureCredential

        credential = DefaultAzureCredential(
            exclude_interactive_browser_credential=False,
        )
        token = credential.get_token("https://cognitiveservices.azure.com/.default")
        speech_config = speechsdk.SpeechConfig(
            auth_token=token.token,
            region=region,
        )

    output_format = cfg.get("output_format", "riff-24khz-16bit-mono-pcm")
    format_enum = getattr(
        speechsdk.SpeechSynthesisOutputFormat,
        output_format.replace("-", "_").capitalize()
        if hasattr(
            speechsdk.SpeechSynthesisOutputFormat, output_format.replace("-", "_").capitalize()
        )
        else "Riff24Khz16BitMonoPcm",
        speechsdk.SpeechSynthesisOutputFormat.Riff24Khz16BitMonoPcm,
    )
    speech_config.set_speech_synthesis_output_format(format_enum)

    output_path = output_dir / "voice.wav"
    audio_config = speechsdk.audio.AudioOutputConfig(filename=str(output_path))
    synthesizer = speechsdk.SpeechSynthesizer(
        speech_config=speech_config, audio_config=audio_config
    )

    ssml = build_ssml(script, cfg)
    logger.info("Synthesizing %d sections via Azure AI Speech", len(script.sections))
    result = synthesizer.speak_ssml_async(ssml).get()

    if result.reason != speechsdk.ResultReason.SynthesizingAudioCompleted:
        cancellation = result.cancellation_details
        msg = f"Azure TTS failed: {result.reason}"
        if cancellation:
            msg += f" — {cancellation.reason}: {cancellation.error_details}"
        raise RuntimeError(msg)

    logger.info("Azure TTS wrote %s", output_path)
    return output_path


def _synthesize_openai(script: TutorialScript, output_dir: Path, cfg: dict) -> Path:
    """Synthesize narration via OpenAI TTS as fallback.

    Attempts per-segment synthesis with ffmpeg concatenation for better
    pacing control.  Falls back to single-blob synthesis if ffmpeg is
    unavailable or concatenation fails.
    """
    import subprocess

    from openai import OpenAI

    client = OpenAI()
    output_path = output_dir / "voice.wav"

    # Define segments: (label, text, trailing_silence_seconds)
    segments: list[tuple[str, str, float]] = [
        ("hook", script.hook, 0.5),
        *((f"section_{i}", s.narration, 0.5) for i, s in enumerate(script.sections)),
        ("recap", script.recap, 0.3),
        ("cta", script.cta, 0.0),
    ]

    segment_paths: list[Path] = []
    try:
        # Synthesize each segment individually
        for name, text, _ in segments:
            seg_path = output_dir / f"_tts_{name}.wav"
            logger.info("Synthesizing segment '%s' via OpenAI TTS", name)
            with client.audio.speech.with_streaming_response.create(
                model=cfg["model"],
                voice=cfg["voice"],
                input=text,
                instructions=cfg.get("instructions", ""),
                response_format=cfg.get("response_format", "wav"),
            ) as response:
                response.stream_to_file(seg_path)
            segment_paths.append(seg_path)

        # Build ffmpeg filter_complex: pad segments with silence then concat
        inputs: list[str] = []
        for seg_path in segment_paths:
            inputs.extend(["-i", str(seg_path)])

        filter_parts: list[str] = []
        labels: list[str] = []
        for i, (_, _, gap) in enumerate(segments):
            if gap > 0:
                filter_parts.append(f"[{i}:a]apad=pad_dur={gap}[a{i}]")
                labels.append(f"[a{i}]")
            else:
                labels.append(f"[{i}:a]")

        n = len(labels)
        filter_parts.append(f"{''.join(labels)}concat=n={n}:v=0:a=1[out]")
        full_filter = ";".join(filter_parts)

        subprocess.run(
            ["ffmpeg", "-y", *inputs, "-filter_complex", full_filter,
             "-map", "[out]", str(output_path)],
            capture_output=True,
            text=True,
            check=True,
        )

        logger.info("OpenAI TTS (per-segment + ffmpeg) wrote %s", output_path)

    except Exception:
        logger.warning(
            "Per-segment synthesis/concat failed, falling back to single-blob approach",
        )

        # Fallback: original single-blob approach
        full_narration = " ".join([
            script.hook,
            *(section.narration for section in script.sections),
            script.recap,
            script.cta,
        ])

        logger.info("Synthesizing via OpenAI TTS (model=%s, voice=%s)", cfg["model"], cfg["voice"])
        with client.audio.speech.with_streaming_response.create(
            model=cfg["model"],
            voice=cfg["voice"],
            input=full_narration,
            instructions=cfg.get("instructions", ""),
            response_format=cfg.get("response_format", "wav"),
        ) as response:
            response.stream_to_file(output_path)

        logger.info("OpenAI TTS wrote %s", output_path)

    finally:
        for seg_path in segment_paths:
            seg_path.unlink(missing_ok=True)

    return output_path
