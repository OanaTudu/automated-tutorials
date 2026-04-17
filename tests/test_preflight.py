"""Tests for src.preflight pre-flight environment checks."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from src.preflight import run_preflight


@pytest.fixture()
def _good_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set all env vars that the default pipeline config requires."""
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com")
    monkeypatch.setenv("AZURE_SPEECH_REGION", "eastus")


AZURE_OPENAI_CONFIG: dict = {
    "script": {"provider": "azure_openai"},
    "tts": {"primary": "azure_speech"},
}

OPENAI_CONFIG: dict = {
    "script": {"provider": "openai"},
    "tts": {"primary": "openai_tts"},
}


class TestLLMProvider:
    """LLM provider env-var checks."""

    def test_missing_azure_openai_endpoint(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("AZURE_OPENAI_ENDPOINT", raising=False)
        with patch("shutil.which", return_value="/usr/bin/ffmpeg"):
            result = run_preflight(AZURE_OPENAI_CONFIG)
        assert any("AZURE_OPENAI_ENDPOINT" in e for e in result.errors)

    def test_missing_openai_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        with patch("shutil.which", return_value="/usr/bin/ffmpeg"):
            result = run_preflight(OPENAI_CONFIG)
        assert any("OPENAI_API_KEY" in e for e in result.errors)


class TestFFmpeg:
    """ffmpeg / ffprobe PATH checks."""

    @pytest.mark.usefixtures("_good_env")
    def test_missing_ffmpeg(self) -> None:
        def _which(name: str) -> str | None:
            return None if name in ("ffmpeg", "ffprobe") else f"/usr/bin/{name}"

        with patch("src.preflight.shutil.which", side_effect=_which):
            result = run_preflight(AZURE_OPENAI_CONFIG)

        ffmpeg_errors = [e for e in result.errors if "ffmpeg" in e or "ffprobe" in e]
        assert len(ffmpeg_errors) == 2


class TestPlaywright:
    """Playwright importability check (warning only)."""

    @pytest.mark.usefixtures("_good_env")
    def test_missing_playwright_is_warning(self) -> None:
        with (
            patch("shutil.which", return_value="/usr/bin/ffmpeg"),
            patch(
                "src.preflight.importlib.import_module",
                side_effect=ModuleNotFoundError,
            ),
        ):
            result = run_preflight(AZURE_OPENAI_CONFIG)

        assert any("playwright" in w for w in result.warnings)
        assert not any("playwright" in e for e in result.errors)


class TestAllGood:
    """Happy-path: every dependency satisfied."""

    @pytest.mark.usefixtures("_good_env")
    def test_no_errors_when_env_is_complete(self) -> None:
        with patch("shutil.which", return_value="/usr/bin/ffmpeg"):
            result = run_preflight(AZURE_OPENAI_CONFIG)

        assert result.errors == []
