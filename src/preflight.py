"""Pre-flight environment checks executed before the pipeline runs."""

from __future__ import annotations

import importlib
import logging
import os
import shutil
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class PreflightResult:
    """Aggregated result of all pre-flight checks."""

    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def run_preflight(config: dict) -> PreflightResult:
    """Validate the runtime environment against *config* requirements.

    Returns a :class:`PreflightResult` whose ``errors`` list contains blocking
    issues and ``warnings`` list contains non-blocking ones.
    """
    result = PreflightResult()

    _check_llm_provider(config, result)
    _check_tts_provider(config, result)
    _check_ffmpeg(result)
    _check_playwright(result)

    for warning in result.warnings:
        logger.warning("Preflight warning: %s", warning)
    for error in result.errors:
        logger.error("Preflight error: %s", error)

    return result


# -- individual checks -------------------------------------------------------


def _check_llm_provider(config: dict, result: PreflightResult) -> None:
    provider = config.get("script", {}).get("provider", "")
    if provider == "azure_openai" and not os.environ.get("AZURE_OPENAI_ENDPOINT"):
        result.errors.append(
            "AZURE_OPENAI_ENDPOINT env var is required when provider is 'azure_openai'"
        )
    elif provider == "openai" and not os.environ.get("OPENAI_API_KEY"):
        result.errors.append(
            "OPENAI_API_KEY env var is required when provider is 'openai'"
        )


def _check_tts_provider(config: dict, result: PreflightResult) -> None:
    primary = config.get("tts", {}).get("primary", "")
    if primary == "azure_speech" and not os.environ.get("AZURE_SPEECH_REGION"):
        result.errors.append(
            "AZURE_SPEECH_REGION env var is required when TTS primary is 'azure_speech'"
        )


def _check_ffmpeg(result: PreflightResult) -> None:
    for binary in ("ffmpeg", "ffprobe"):
        if shutil.which(binary) is None:
            result.errors.append(f"'{binary}' not found on PATH")


def _check_playwright(result: PreflightResult) -> None:
    try:
        importlib.import_module("playwright")
    except ModuleNotFoundError:
        result.warnings.append(
            "'playwright' is not installed; recording will use placeholder mode"
        )
