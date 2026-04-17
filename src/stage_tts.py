"""Voice synthesis stage with Azure AI Speech primary and OpenAI TTS fallback."""

from __future__ import annotations

import logging
from pathlib import Path

from .ffmpeg_helpers import probe_audio_duration_ms
from .models import StageResult, TimingManifest, TimingSegment, TutorialScript
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
        output_path, manifest = _dispatch(primary, script, output_dir, tts_cfg)
    except Exception as primary_err:
        logger.warning("Primary TTS (%s) failed, falling back to %s", primary, fallback)
        try:
            output_path, manifest = _dispatch(fallback, script, output_dir, tts_cfg)
        except Exception as fallback_err:
            raise RuntimeError(
                f"All TTS providers failed.\n"
                f"  Primary ({primary}): {primary_err}\n"
                f"  Fallback ({fallback}): {fallback_err}"
            ) from fallback_err

    manifest_path = output_dir / "timing_manifest.json"
    manifest_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    logger.info("Wrote timing manifest to %s", manifest_path)

    return StageResult(
        stage="tts",
        success=True,
        output_path=str(output_path),
        metadata={"manifest_path": str(manifest_path)},
    )


def _dispatch(
    provider: str, script: TutorialScript, output_dir: Path, tts_cfg: dict,
) -> tuple[Path, TimingManifest]:
    """Route to the correct provider implementation."""
    if provider in ("azure_speech", "azure"):
        return _synthesize_azure(script, output_dir, tts_cfg["azure"])
    if provider in ("openai_tts", "openai"):
        return _synthesize_openai(script, output_dir, tts_cfg["openai"])
    msg = f"Unknown TTS provider: {provider}"
    raise ValueError(msg)


def _synthesize_azure(
    script: TutorialScript, output_dir: Path, cfg: dict,
) -> tuple[Path, TimingManifest]:
    """Synthesize narration via Azure AI Speech SDK with SSML."""
    import os

    try:
        import azure.cognitiveservices.speech as speechsdk
    except ImportError as exc:
        raise RuntimeError(
            "Azure Speech SDK not installed. "
            "Run: pip install azure-cognitiveservices-speech"
        ) from exc

    region = os.environ.get("AZURE_SPEECH_REGION")
    if not region:
        raise RuntimeError("Azure Speech requires AZURE_SPEECH_REGION env var")
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

    # Capture bookmark events emitted by <mark> tags in the SSML
    bookmarks: dict[str, int] = {}

    def _on_bookmark(evt: speechsdk.SpeechSynthesisBookmarkEventArgs) -> None:
        bookmarks[evt.text] = evt.audio_offset // 10_000  # 100-ns ticks → ms

    synthesizer.bookmark_reached.connect(_on_bookmark)

    ssml = build_ssml(script, cfg)
    logger.info("Synthesizing %d sections via Azure AI Speech", len(script.sections))
    result = synthesizer.speak_ssml_async(ssml).get()

    if result.reason != speechsdk.ResultReason.SynthesizingAudioCompleted:
        cancellation = result.cancellation_details
        msg = f"Azure TTS failed: {result.reason}"
        if cancellation:
            msg += f" — {cancellation.reason}: {cancellation.error_details}"
        raise RuntimeError(msg)

    # Build timing manifest from captured bookmarks
    segment_ids = [k.removesuffix("_start") for k in bookmarks if k.endswith("_start")]
    segments: list[TimingSegment] = []
    for seg_id in segment_ids:
        start_key = f"{seg_id}_start"
        end_key = f"{seg_id}_end"
        if start_key in bookmarks and end_key in bookmarks:
            segments.append(TimingSegment(
                id=seg_id,
                start_ms=bookmarks[start_key],
                end_ms=bookmarks[end_key],
            ))

    total_ms = (
        int(result.audio_duration.total_seconds() * 1000)
        if result.audio_duration
        else (segments[-1].end_ms if segments else 0)
    )
    manifest = TimingManifest(total_duration_ms=total_ms, segments=segments)

    logger.info("Azure TTS wrote %s (%d segments in manifest)", output_path, len(segments))
    return output_path, manifest


def _synthesize_openai(
    script: TutorialScript, output_dir: Path, cfg: dict,
) -> tuple[Path, TimingManifest]:
    """Synthesize narration via OpenAI TTS as fallback.

    Attempts per-segment synthesis with ffmpeg concatenation for better
    pacing control.  Falls back to single-blob synthesis if ffmpeg is
    unavailable or concatenation fails.
    """
    import os
    import subprocess

    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError(
            "OpenAI TTS requires OPENAI_API_KEY env var. "
            "Set it or configure Azure Speech as primary."
        )

    from openai import OpenAI

    client = OpenAI()
    output_path = output_dir / "voice.wav"

    # Define segments: (id, text, target_seconds)
    segment_infos: list[dict] = [
        {"id": "hook", "text": script.hook, "target_sec": 5.0},
        *[
            {"id": f"section_{i}", "text": s.narration, "target_sec": float(s.target_seconds)}
            for i, s in enumerate(script.sections)
        ],
        {"id": "recap", "text": script.recap, "target_sec": 5.0},
        {"id": "cta", "text": script.cta, "target_sec": 0.0},
    ]

    segment_paths: list[Path] = []
    manifest = TimingManifest(total_duration_ms=0, segments=[])
    try:
        # Synthesize each segment individually
        for info in segment_infos:
            seg_path = output_dir / f"_tts_{info['id']}.wav"
            logger.info("Synthesizing segment '%s' via OpenAI TTS", info["id"])
            with client.audio.speech.with_streaming_response.create(
                model=cfg["model"],
                voice=cfg["voice"],
                input=info["text"],
                instructions=cfg.get("instructions", ""),
                response_format=cfg.get("response_format", "wav"),
            ) as response:
                response.stream_to_file(seg_path)
            segment_paths.append(seg_path)

        # Probe actual durations and build timing manifest
        durations_ms: list[int] = []
        for seg_path in segment_paths:
            durations_ms.append(probe_audio_duration_ms(seg_path))

        segments: list[TimingSegment] = []
        cumulative_ms = 0
        slot_secs: list[float] = []
        for i, info in enumerate(segment_infos):
            dur_ms = durations_ms[i]
            segments.append(TimingSegment(
                id=info["id"],
                start_ms=cumulative_ms,
                end_ms=cumulative_ms + dur_ms,
                text=info["text"],
            ))
            # Compute slot: use target_sec if it exceeds the audio, otherwise audio + tail
            target_ms = int(info["target_sec"] * 1000)
            slot_ms = max(target_ms, dur_ms + 500) if i + 1 < len(segment_infos) else dur_ms
            slot_sec = slot_ms / 1000
            slot_secs.append(slot_sec)
            cumulative_ms += slot_ms

        manifest = TimingManifest(total_duration_ms=cumulative_ms, segments=segments)

        # Build ffmpeg filter_complex: pad each segment to fill its timeslot
        inputs: list[str] = []
        for seg_path in segment_paths:
            inputs.extend(["-i", str(seg_path)])

        filter_parts: list[str] = []
        labels: list[str] = []
        for i, slot_sec in enumerate(slot_secs):
            if i + 1 < len(slot_secs):
                filter_parts.append(f"[{i}:a]apad=whole_dur={slot_sec:.3f}[a{i}]")
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

        # Fallback: original single-blob approach (no manifest granularity)
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

        # Single-blob fallback: one segment covering the whole output
        manifest = TimingManifest(
            total_duration_ms=0,
            segments=[TimingSegment(id="full", start_ms=0, end_ms=0, text=full_narration)],
        )
        logger.info("OpenAI TTS wrote %s", output_path)

    finally:
        for seg_path in segment_paths:
            seg_path.unlink(missing_ok=True)

    return output_path, manifest
