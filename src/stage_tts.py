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
    if provider in ("azure_openai_tts", "azure_openai"):
        return _synthesize_azure_openai(script, output_dir, tts_cfg["openai"])
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
        from azure.identity import AzureCliCredential

        credential = AzureCliCredential()
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


def _synthesize_azure_openai(
    script: TutorialScript, output_dir: Path, cfg: dict,
) -> tuple[Path, TimingManifest]:
    """Synthesize narration via Azure OpenAI TTS using DefaultAzureCredential."""
    import os

    from azure.identity import AzureCliCredential, get_bearer_token_provider
    from openai import AzureOpenAI

    endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")
    if not endpoint:
        raise RuntimeError("Azure OpenAI TTS requires AZURE_OPENAI_ENDPOINT env var")

    token_provider = get_bearer_token_provider(
        AzureCliCredential(),
        "https://cognitiveservices.azure.com/.default",
    )
    client = AzureOpenAI(
        azure_endpoint=endpoint,
        azure_ad_token_provider=token_provider,
        api_version="2025-04-01-preview",
    )
    return _synthesize_with_client(client, script, output_dir, cfg)


def _synthesize_openai(
    script: TutorialScript, output_dir: Path, cfg: dict,
) -> tuple[Path, TimingManifest]:
    """Synthesize narration via OpenAI TTS as fallback."""
    import os

    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError(
            "OpenAI TTS requires OPENAI_API_KEY env var. "
            "Set it or configure Azure Speech as primary."
        )

    from openai import OpenAI

    client = OpenAI()
    return _synthesize_with_client(client, script, output_dir, cfg)


def _synthesize_with_client(
    client: "OpenAI",
    script: TutorialScript,
    output_dir: Path,
    cfg: dict,
) -> tuple[Path, TimingManifest]:
    """Shared TTS logic for both OpenAI and Azure OpenAI clients.

    Attempts per-segment synthesis with ffmpeg concatenation for better
    pacing control.  Falls back to single-blob synthesis if ffmpeg is
    unavailable or concatenation fails.
    """
    import subprocess

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
    gap_path: Path | None = None
    concat_list: Path | None = None
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
        for i, info in enumerate(segment_infos):
            dur_ms = durations_ms[i]
            segments.append(TimingSegment(
                id=info["id"],
                start_ms=cumulative_ms,
                end_ms=cumulative_ms + dur_ms,
                text=info["text"],
            ))
            cumulative_ms += dur_ms

        manifest = TimingManifest(total_duration_ms=cumulative_ms, segments=segments)

        # Build ffmpeg concat: join segments with short silence gaps (no padding)
        GAP_SEC = 1.5
        gap_path = output_dir / "_tts_gap.wav"
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=mono",
             "-t", str(GAP_SEC), "-c:a", "pcm_s16le", str(gap_path)],
            capture_output=True, check=True,
        )

        concat_list = output_dir / "_tts_concat.txt"
        lines: list[str] = []
        tight_segments: list[TimingSegment] = []
        tight_cursor_ms = 0
        for i, (seg_path, info) in enumerate(zip(segment_paths, segment_infos)):
            if i > 0:
                lines.append(f"file '{gap_path.resolve()}'")
                tight_cursor_ms += int(GAP_SEC * 1000)
            lines.append(f"file '{seg_path.resolve()}'")
            dur_ms = durations_ms[i]
            tight_segments.append(TimingSegment(
                id=info["id"],
                start_ms=tight_cursor_ms,
                end_ms=tight_cursor_ms + dur_ms,
                text=info["text"],
            ))
            tight_cursor_ms += dur_ms

        concat_list.write_text("\n".join(lines), encoding="utf-8")
        subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
             "-i", str(concat_list.resolve()), "-c:a", "pcm_s16le",
             str(output_path.resolve())],
            capture_output=True, check=True,
            cwd=str(output_dir.resolve()),
        )

        # Update manifest with tight timing (no padding)
        manifest = TimingManifest(
            total_duration_ms=tight_cursor_ms, segments=tight_segments,
        )

        # Cleanup temp files
        for f in segment_paths:
            f.unlink(missing_ok=True)
        gap_path.unlink(missing_ok=True)
        concat_list.unlink(missing_ok=True)

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
        if gap_path is not None:
            gap_path.unlink(missing_ok=True)
        if concat_list is not None:
            concat_list.unlink(missing_ok=True)

    return output_path, manifest
