"""Live API test stubs — gated by environment variables and the 'live' marker."""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.live


@pytest.fixture()
def has_openai_key():
    """Skip when OPENAI_API_KEY is not set."""
    if not os.environ.get("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY not set")


@pytest.fixture()
def has_azure_speech_key():
    """Skip when AZURE_SPEECH_KEY is not set."""
    if not os.environ.get("AZURE_SPEECH_KEY"):
        pytest.skip("AZURE_SPEECH_KEY not set")


class TestLiveOpenAI:
    def test_tts_produces_audio(self, has_openai_key):
        pytest.skip("Implement when ready")


class TestLiveAzureSpeech:
    def test_ssml_synthesis(self, has_azure_speech_key):
        pytest.skip("Implement when ready")
