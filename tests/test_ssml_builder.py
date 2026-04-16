"""Tests for ssml_builder.build_ssml — pure logic, validates XML structure."""

from __future__ import annotations

import xml.etree.ElementTree as ET

from src.ssml_builder import build_ssml

# ── Helpers ──────────────────────────────────────────────────────────────

_NS = {
    "s": "http://www.w3.org/2001/10/synthesis",
    "mstts": "https://www.w3.org/2001/mstts",
}


def _default_cfg() -> dict:
    return {
        "voice": "en-US-AvaMultilingualNeural",
        "style": "narration-professional",
        "style_degree": "1.1",
        "speaking_rate": "-5%",
    }


# ── Basic structure ──────────────────────────────────────────────────────


def test_ssml_is_well_formed_xml(sample_script):
    ssml = build_ssml(sample_script, _default_cfg())
    # Should parse without raising
    ET.fromstring(ssml)


def test_ssml_contains_speak_root(sample_script):
    ssml = build_ssml(sample_script, _default_cfg())
    root = ET.fromstring(ssml)
    assert root.tag == "{http://www.w3.org/2001/10/synthesis}speak"


def test_ssml_contains_voice_element(sample_script):
    ssml = build_ssml(sample_script, _default_cfg())
    root = ET.fromstring(ssml)
    voices = root.findall("s:voice", _NS)
    assert len(voices) == 1
    assert voices[0].attrib["name"] == "en-US-AvaMultilingualNeural"


def test_ssml_contains_express_as(sample_script):
    ssml = build_ssml(sample_script, _default_cfg())
    root = ET.fromstring(ssml)
    express = root.findall(".//mstts:express-as", _NS)
    assert len(express) == 1
    assert express[0].attrib["style"] == "narration-professional"


# ── Content inclusion ────────────────────────────────────────────────────


def test_ssml_includes_hook(sample_script):
    ssml = build_ssml(sample_script, _default_cfg())
    assert sample_script.hook in ssml or "learn Python" in ssml


def test_ssml_includes_all_sections(sample_script):
    ssml = build_ssml(sample_script, _default_cfg())
    for section in sample_script.sections:
        assert section.narration in ssml


def test_ssml_includes_recap_and_cta(sample_script):
    ssml = build_ssml(sample_script, _default_cfg())
    assert sample_script.recap in ssml
    assert sample_script.cta in ssml


# ── XML safety ───────────────────────────────────────────────────────────


def test_ssml_escapes_special_characters(sample_script):
    """Script text with <, >, & must not break SSML well-formedness."""
    sample_script.hook = "Use <script> & 'quotes' in templates"
    ssml = build_ssml(sample_script, _default_cfg())
    # Must still parse as valid XML
    ET.fromstring(ssml)
    # Raw < and & should not appear in the text nodes
    assert "<script>" not in ssml
    assert "&lt;script&gt;" in ssml


# ── Prosody config ───────────────────────────────────────────────────────


def test_ssml_uses_custom_speaking_rate(sample_script):
    cfg = _default_cfg()
    cfg["speaking_rate"] = "+10%"
    ssml = build_ssml(sample_script, cfg)
    assert "+10%" in ssml


def test_ssml_uses_default_style_when_not_configured(sample_script):
    cfg = {"voice": "en-US-AvaMultilingualNeural"}
    ssml = build_ssml(sample_script, cfg)
    assert "narration-professional" in ssml
