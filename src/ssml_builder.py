"""SSML template builder for Azure AI Speech synthesis."""

from __future__ import annotations

import re
from xml.sax.saxutils import escape

from .models import TutorialScript

_CODE_KEYWORDS = frozenset({
    "code", "implement", "function", "class", "import",
    "terminal", "command", "syntax",
})


def _compute_slower_rate(rate: str) -> str:
    """Return a rate string 5 percentage points slower than *rate*."""
    match = re.match(r"([+-]?\d+)%", rate)
    if not match:
        return rate
    value = int(match.group(1)) - 5
    sign = "+" if value > 0 else ""
    return f"{sign}{value}%"


def _is_code_section(title: str, narration: str) -> bool:
    """True when section text contains code-related keywords."""
    combined = f"{title} {narration}".lower()
    return any(kw in combined for kw in _CODE_KEYWORDS)


def _add_emphasis(text: str, key_points: list[str]) -> str:
    """Wrap first occurrence of short key-point terms with SSML emphasis.

    Only key_points of 1–3 words are considered.  *text* must already be
    XML-escaped; key_point values are escaped before matching so the
    returned string remains well-formed SSML.
    """
    for kp in key_points:
        if not (1 <= len(kp.split()) <= 3):
            continue
        escaped_kp = escape(kp)
        pattern = re.compile(re.escape(escaped_kp), re.IGNORECASE)
        text = pattern.sub(
            f'<emphasis level="moderate">{escaped_kp}</emphasis>',
            text,
            count=1,
        )
    return text


def build_ssml(script: TutorialScript, cfg: dict) -> str:
    """Build a well-formed SSML document from script sections.

    Parameters
    ----------
    script:
        Tutorial script containing hook, sections, recap, and cta.
    cfg:
        Azure TTS configuration with voice, style, style_degree,
        and speaking_rate keys.

    Returns
    -------
    str
        Complete SSML string ready for Azure Speech SDK.
    """
    voice = cfg["voice"]
    style = cfg.get("style", "narration-professional")
    degree = cfg.get("style_degree", "1.0")
    rate = cfg.get("speaking_rate", "-5%")
    slow_rate = _compute_slower_rate(rate)

    parts: list[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" '
        'xmlns:mstts="https://www.w3.org/2001/mstts" xml:lang="en-US">',
        f'  <voice name="{escape(voice)}">',
        f'    <mstts:express-as style="{escape(style)}" styledegree="{escape(str(degree))}">',
    ]

    # Hook
    parts.append(f'      <prosody rate="{escape(rate)}">{escape(script.hook)}</prosody>')
    parts.append('      <break time="500ms"/>')

    # Sections — code-heavy sections use a slower rate
    for section in script.sections:
        section_rate = slow_rate if _is_code_section(section.title, section.narration) else rate
        narration = _add_emphasis(escape(section.narration), section.key_points)
        parts.append(f'      <prosody rate="{escape(section_rate)}">{narration}</prosody>')
        parts.append('      <break time="600ms"/>')

    # Breathing room before recap
    parts.append('      <break time="400ms"/>')

    # Recap and CTA
    parts.append(f'      <prosody rate="{escape(rate)}">{escape(script.recap)}</prosody>')
    parts.append('      <break time="300ms"/>')
    parts.append(f'      <prosody rate="{escape(rate)}">{escape(script.cta)}</prosody>')

    parts.append("    </mstts:express-as>")
    parts.append("  </voice>")
    parts.append("</speak>")

    return "\n".join(parts)
