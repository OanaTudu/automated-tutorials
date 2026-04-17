"""Generate visual slide images from tutorial script data and compose them into a video.

Workflow:
1. Build styled HTML for each timing segment (title, section, recap, CTA).
2. Screenshot each HTML slide at 1920×1080 with Playwright (headless).
3. Compose screenshots into a single H.264 MP4 using ffmpeg concat demuxer,
   with each slide displayed for the duration of its corresponding segment.
"""

from __future__ import annotations

import html
import logging
import re
import shutil
import subprocess
from pathlib import Path

from .models import TimingManifest, TutorialScript

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_WIDTH = 1920
_HEIGHT = 1080

_CSS = """\
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
    width: 1920px; height: 1080px; overflow: hidden;
    font-family: 'Segoe UI', 'Inter', 'Helvetica Neue', Arial, sans-serif;
    color: #e8ecf1;
}
.slide {
    width: 1920px; height: 1080px; padding: 80px 100px;
    display: flex; flex-direction: column; justify-content: center;
}
/* Title slide */
.slide-title {
    background: linear-gradient(135deg, #0f1b2d 0%, #1a2a4a 50%, #0f1b2d 100%);
    text-align: center; align-items: center;
}
.slide-title h1 {
    font-size: 64px; font-weight: 700; line-height: 1.2;
    margin-bottom: 32px; color: #ffffff;
}
.slide-title .subtitle {
    font-size: 30px; color: #8fa4c4; font-weight: 400;
}
/* Section slide */
.slide-section {
    background: linear-gradient(160deg, #101c30 0%, #182848 100%);
}
.slide-section .section-header {
    font-size: 18px; text-transform: uppercase; letter-spacing: 3px;
    color: #5b8dd9; margin-bottom: 12px;
}
.slide-section h2 {
    font-size: 48px; font-weight: 700; margin-bottom: 40px; color: #ffffff;
}
.slide-section ul {
    list-style: none; padding: 0;
}
.slide-section ul li {
    font-size: 28px; line-height: 1.6; padding: 8px 0 8px 36px;
    position: relative; color: #c8d6e8;
}
.slide-section ul li::before {
    content: '▸'; position: absolute; left: 0; color: #5b8dd9;
}
.on-screen-text {
    margin-top: 36px; padding: 20px 28px;
    background: rgba(91,141,217,0.12); border-left: 4px solid #5b8dd9;
    font-size: 26px; color: #a8c4e8; border-radius: 4px;
}
/* Code block */
.code-block {
    margin-top: 32px; padding: 24px 28px;
    background: #0d1117; border: 1px solid #30363d; border-radius: 8px;
    overflow: hidden; max-height: 400px;
}
.code-block pre {
    margin: 0; font-family: 'Cascadia Code', 'Fira Code', 'Consolas', monospace;
    font-size: 20px; line-height: 1.5; color: #c9d1d9;
    white-space: pre-wrap; word-break: break-word;
}
/* Recap slide */
.slide-recap {
    background: linear-gradient(160deg, #101c30 0%, #182848 100%);
}
.slide-recap h2 {
    font-size: 52px; font-weight: 700; margin-bottom: 48px; color: #ffffff;
}
.slide-recap ul { list-style: none; padding: 0; }
.slide-recap ul li {
    font-size: 30px; line-height: 1.7; padding: 8px 0 8px 40px;
    position: relative; color: #c8d6e8;
}
.slide-recap ul li::before {
    content: '✓'; position: absolute; left: 0; color: #4ade80;
}
/* CTA slide */
.slide-cta {
    background: linear-gradient(135deg, #162544 0%, #1e3a6e 50%, #162544 100%);
    text-align: center; align-items: center;
}
.slide-cta h2 {
    font-size: 52px; font-weight: 700; margin-bottom: 36px; color: #ffffff;
}
.slide-cta p {
    font-size: 32px; color: #a8c4e8; max-width: 1200px; line-height: 1.5;
}
"""

# Python keyword list for lightweight syntax highlighting
_PY_KEYWORDS = (
    r"\b(def|class|import|from|return|if|elif|else|for|while|try|except|finally|"
    r"with|as|raise|yield|pass|break|continue|and|or|not|in|is|None|True|False|"
    r"lambda|async|await|self)\b"
)


# ---------------------------------------------------------------------------
# HTML generation helpers
# ---------------------------------------------------------------------------


def _esc(text: str) -> str:
    """HTML-escape text."""
    return html.escape(text, quote=True)


def _wrap_html(body: str) -> str:
    """Wrap a slide body in a full HTML document."""
    return (
        "<!DOCTYPE html>\n<html><head><meta charset='utf-8'>"
        f"<style>{_CSS}</style></head><body>{body}</body></html>"
    )


def _highlight_code(code: str) -> str:
    """Apply lightweight syntax coloring via inline ``<span>`` styles.

    Highlighting is applied on raw text using sentinel markers, *then*
    the non-marker portions are HTML-escaped.  This avoids the previous
    bug where ``#`` inside HTML entities (e.g. ``&#x27;``) was mistakenly
    treated as a comment delimiter.
    """
    sentinel_s = "\x02"  # sentinel start
    sentinel_e = "\x03"  # sentinel end

    # 1. Apply regex highlighting on RAW code using sentinels
    # Comments: # at start-of-line or after whitespace
    code = re.sub(
        r"((?:^|\s)#[^\n]*)",
        sentinel_s + 'C' + sentinel_e + r"\1" + sentinel_s + '/' + sentinel_e,
        code,
    )
    # Strings (single/double, non-greedy)
    code = re.sub(
        r"""(".*?"|'.*?')""",
        sentinel_s + 'S' + sentinel_e + r"\1" + sentinel_s + '/' + sentinel_e,
        code,
    )
    # Keywords
    code = re.sub(
        _PY_KEYWORDS,
        sentinel_s + 'K' + sentinel_e + r"\1" + sentinel_s + '/' + sentinel_e,
        code,
    )
    # JS keywords (function, const, let, var, export, default, import)
    code = re.sub(
        r"\b(function|const|let|var|export|default|import)\b",
        sentinel_s + 'K' + sentinel_e + r"\1" + sentinel_s + '/' + sentinel_e,
        code,
    )

    # 2. HTML-escape everything (sentinels survive because they are control chars)
    escaped = _esc(code)

    # 3. Replace sentinels with real HTML spans
    span_map = {
        'C': '<span style="color:#6a737d">',   # comments
        'S': '<span style="color:#a5d6a7">',   # strings
        'K': '<span style="color:#79b8ff">',    # keywords
        '/': '</span>',
    }
    for tag, replacement in span_map.items():
        escaped = escaped.replace(sentinel_s + tag + sentinel_e, replacement)

    return escaped


def _extract_code_from_text(text: str) -> str | None:
    """Extract the first fenced code block (``` ... ```) from *text*."""
    match = re.search(r"```(?:\w+)?\n(.*?)```", text, re.DOTALL)
    return match.group(1).strip() if match else None


def _build_title_slide(script: TutorialScript) -> str:
    return _wrap_html(
        f'<div class="slide slide-title">'
        f"<h1>{_esc(script.topic)}</h1>"
        f'<div class="subtitle">A tutorial for {_esc(script.audience)}</div>'
        f"</div>"
    )


def _build_section_slide(
    section_idx: int,
    script: TutorialScript,
    code_snippet: str | None,
) -> str:
    section = script.sections[section_idx]
    bullets = "".join(f"<li>{_esc(kp)}</li>" for kp in section.key_points)

    on_screen = ""
    for shot in section.shots:
        if shot.on_screen_text:
            on_screen = (
                f'<div class="on-screen-text">{_esc(shot.on_screen_text)}</div>'
            )
            break

    # Prefer explicit code_snippet; fall back to code fenced block in narration
    code_html = ""
    code = code_snippet or _extract_code_from_text(section.narration)
    if code:
        code_html = (
            f'<div class="code-block"><pre><code>'
            f"{_highlight_code(code)}</code></pre></div>"
        )

    return _wrap_html(
        f'<div class="slide slide-section">'
        f'<div class="section-header">Section {section_idx + 1}</div>'
        f"<h2>{_esc(section.title)}</h2>"
        f"<ul>{bullets}</ul>"
        f"{on_screen}"
        f"{code_html}"
        f"</div>"
    )


def _build_recap_slide(script: TutorialScript) -> str:
    items = "".join(f"<li>{_esc(s.title)}</li>" for s in script.sections)
    return _wrap_html(
        f'<div class="slide slide-recap">'
        f"<h2>Recap</h2>"
        f"<ul>{items}</ul>"
        f"</div>"
    )


def _build_cta_slide(script: TutorialScript) -> str:
    return _wrap_html(
        f'<div class="slide slide-cta">'
        f"<h2>Thanks for watching!</h2>"
        f"<p>{_esc(script.cta)}</p>"
        f"</div>"
    )


# ---------------------------------------------------------------------------
# Slide generation (orchestrator)
# ---------------------------------------------------------------------------


def _strip_fences(snippet: str) -> str:
    """Remove markdown fence markers (` ```lang ... ``` `) and return bare code."""
    match = re.search(r"```(?:\w+)?\n(.*?)```", snippet, re.DOTALL)
    return match.group(1).strip() if match else snippet.strip()


def _detect_language(snippet: str) -> str:
    """Best-effort language detection from a fenced code block."""
    m = re.match(r"```(\w+)", snippet)
    if m:
        return m.group(1).lower()
    # Heuristic fallback
    if "def " in snippet or "import " in snippet and "from " in snippet:
        return "python"
    if "function " in snippet or "const " in snippet or "=>" in snippet:
        return "javascript"
    return "unknown"


def _distribute_code_examples(
    script: TutorialScript,
    research_data: dict | None,
) -> dict[int, str]:
    """Map section indices to code snippets from *research_data*.

    Matches by language hint: sections mentioning "Python" get Python
    examples, sections mentioning "React"/"JavaScript" get JS examples.
    """
    raw_examples: list[str] = []
    if research_data:
        raw_examples = list(research_data.get("code_examples", []))

    if not raw_examples:
        return {}

    # Classify examples by language
    tagged: list[tuple[str, str]] = [
        (_detect_language(ex), _strip_fences(ex)) for ex in raw_examples
    ]

    mapping: dict[int, str] = {}
    used: set[int] = set()

    # First pass: match by language affinity
    for idx, section in enumerate(script.sections):
        narration_lower = section.narration.lower()
        want_py = any(kw in narration_lower for kw in ("python", "flask", "django", "pip"))
        want_js = any(
            kw in narration_lower
            for kw in ("javascript", "react", "hook system", "usestate", "node")
        )

        for ex_idx, (lang, code) in enumerate(tagged):
            if ex_idx in used:
                continue
            if want_py and lang == "python":
                mapping[idx] = code
                used.add(ex_idx)
                break
            if want_js and lang in ("javascript", "js", "jsx", "typescript"):
                mapping[idx] = code
                used.add(ex_idx)
                break

    # Second pass: distribute remaining examples to code-hinting sections
    for idx, section in enumerate(script.sections):
        if idx in mapping:
            continue
        narration_lower = section.narration.lower()
        has_code_hint = any(
            kw in narration_lower
            for kw in ("code", "example", "snippet", "import", "function", "class", "def ")
        )
        if has_code_hint:
            for ex_idx, (_, code) in enumerate(tagged):
                if ex_idx not in used:
                    mapping[idx] = code
                    used.add(ex_idx)
                    break

    return mapping


def _generate_slide_html(
    script: TutorialScript,
    research_data: dict | None,
) -> dict[str, str]:
    """Return a mapping of segment ID → HTML string for each slide.

    Keys match the ``TimingSegment.id`` values: ``"hook"``, ``"section_0"``, …,
    ``"recap"``, ``"cta"``.
    """
    code_map = _distribute_code_examples(script, research_data)

    slides: dict[str, str] = {
        "hook": _build_title_slide(script),
    }

    for idx in range(len(script.sections)):
        slides[f"section_{idx}"] = _build_section_slide(
            idx, script, code_map.get(idx),
        )

    slides["recap"] = _build_recap_slide(script)
    slides["cta"] = _build_cta_slide(script)
    return slides


# ---------------------------------------------------------------------------
# Playwright screenshotting
# ---------------------------------------------------------------------------


def _screenshot_slides(
    slides: dict[str, str],
    output_dir: Path,
) -> dict[str, Path]:
    """Render each HTML slide in a headless browser and save a 1920×1080 PNG.

    Returns a mapping of segment ID → PNG file path.

    Raises
    ------
    ImportError
        If the ``playwright`` package is not installed.
    RuntimeError
        If Playwright browsers are not installed.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise ImportError(
            "Playwright is required for slide rendering. "
            "Install it with: pip install playwright && python -m playwright install chromium"
        ) from None

    image_paths: dict[str, Path] = {}
    logger.info("Screenshotting %d slides with Playwright …", len(slides))

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": _WIDTH, "height": _HEIGHT})

        for seg_id, html_content in slides.items():
            png_path = output_dir / f"slide_{seg_id}.png"
            page.set_content(html_content, wait_until="load")
            page.screenshot(path=str(png_path), full_page=False)
            image_paths[seg_id] = png_path
            logger.debug("  → %s", png_path.name)

        browser.close()

    logger.info("All slides screenshotted.")
    return image_paths


# ---------------------------------------------------------------------------
# Keyframe-based screenshotting (visual engine path)
# ---------------------------------------------------------------------------


def _screenshot_keyframes(
    keyframes: list,
    output_dir: Path,
) -> tuple[list[Path], list[float]]:
    """Screenshot each keyframe and return (image_paths, durations_sec).

    Parameters
    ----------
    keyframes:
        List of ``Keyframe`` objects from :mod:`visual_engine`, each with
        ``.html`` (str) and ``.duration_ms`` (int).
    output_dir:
        Directory where PNG files are written.

    Returns
    -------
    tuple[list[Path], list[float]]
        Parallel lists of PNG file paths and their durations in seconds.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise ImportError(
            "Playwright is required for keyframe rendering. "
            "Install it with: pip install playwright && python -m playwright install chromium"
        ) from None

    image_paths: list[Path] = []
    durations: list[float] = []

    logger.info("Screenshotting %d keyframes with Playwright …", len(keyframes))

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": _WIDTH, "height": _HEIGHT})

        for idx, kf in enumerate(keyframes):
            png_path = output_dir / f"kf_{idx:04d}_{kf.shot_id}.png"
            page.set_content(kf.html, wait_until="load")
            page.screenshot(path=str(png_path), full_page=False)
            image_paths.append(png_path)
            durations.append(kf.duration_ms / 1000.0)

        browser.close()

    logger.info("All %d keyframes screenshotted.", len(keyframes))
    return image_paths, durations


def _compose_keyframe_video(
    image_paths: list[Path],
    durations: list[float],
    output_dir: Path,
) -> Path:
    """Stitch keyframe PNGs into a single MP4 using the ffmpeg concat demuxer.

    Parameters
    ----------
    image_paths:
        Ordered list of PNG file paths.
    durations:
        Parallel list of display durations in seconds.
    output_dir:
        Directory for intermediate files and the output video.

    Returns
    -------
    Path
        Path to the output ``slides_video.mp4``.
    """
    if not shutil.which("ffmpeg"):
        raise FileNotFoundError(
            "ffmpeg not found on PATH. Install it with: winget install ffmpeg"
        )

    concat_lines: list[str] = []
    for img_path, dur in zip(image_paths, durations):
        concat_lines.append(f"file '{img_path.name}'")
        concat_lines.append(f"duration {dur:.3f}")

    # ffmpeg concat requires last file repeated without duration
    if image_paths:
        concat_lines.append(f"file '{image_paths[-1].name}'")

    concat_path = output_dir / "concat_list.txt"
    concat_path.write_text("\n".join(concat_lines), encoding="utf-8")

    video_path = output_dir / "slides_video.mp4"
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(concat_path.resolve()),
        "-vf", "fps=30",
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "23",
        "-pix_fmt", "yuv420p",
        str(video_path.resolve()),
    ]
    logger.info("Composing keyframe video (%d frames) …", len(image_paths))

    result = subprocess.run(
        cmd, capture_output=True, text=True, cwd=str(output_dir.resolve()),
    )
    if result.returncode != 0:
        logger.error("ffmpeg stderr:\n%s", result.stderr)
        result.check_returncode()

    logger.info("Keyframe video created: %s", video_path)
    return video_path


# ---------------------------------------------------------------------------
# ffmpeg video composition (legacy static slides)
# ---------------------------------------------------------------------------


def _compose_slide_video(
    image_paths: dict[str, Path],
    timing_manifest: TimingManifest,
    output_dir: Path,
) -> Path:
    """Stitch slide PNGs into a single MP4 using the ffmpeg concat demuxer.

    Each slide is displayed from its segment start until the next segment's
    start (covering any inter-segment gaps).  The final slide extends to the
    total video duration.

    Raises
    ------
    FileNotFoundError
        If ``ffmpeg`` is not on ``PATH``.
    subprocess.CalledProcessError
        If the ffmpeg process exits with a non-zero code.
    """
    if not shutil.which("ffmpeg"):
        raise FileNotFoundError(
            "ffmpeg not found on PATH. Install it with: winget install ffmpeg"
        )

    total_duration_sec = timing_manifest.total_duration_ms / 1000.0
    segments = timing_manifest.segments

    # Build concat list.  Each entry holds the previous slide until the next
    # segment starts, so gaps between segments are naturally filled.
    concat_lines: list[str] = []
    for i, seg in enumerate(segments):
        seg_id = seg.id
        if seg_id not in image_paths:
            logger.warning("No slide image for segment '%s' — skipping", seg_id)
            continue

        # Use forward slashes in the concat file for cross-platform safety
        img_rel = image_paths[seg_id].name
        start_sec = seg.start_ms / 1000.0

        if i + 1 < len(segments):
            next_start_sec = segments[i + 1].start_ms / 1000.0
        else:
            next_start_sec = total_duration_sec

        duration = next_start_sec - start_sec
        if duration <= 0:
            duration = 0.1  # safety floor

        concat_lines.append(f"file '{img_rel}'")
        concat_lines.append(f"duration {duration:.3f}")

    # ffmpeg concat demuxer requires the last file repeated without duration
    if segments and segments[-1].id in image_paths:
        last_img = image_paths[segments[-1].id].name
        concat_lines.append(f"file '{last_img}'")

    concat_path = output_dir / "concat_list.txt"
    concat_path.write_text("\n".join(concat_lines), encoding="utf-8")
    logger.debug("Concat list written to %s", concat_path)

    video_path = output_dir / "slides_video.mp4"
    # Use absolute paths so cwd doesn't conflict with relative path resolution
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(concat_path.resolve()),
        "-vf", "fps=30",
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "23",
        "-pix_fmt", "yuv420p",
        str(video_path.resolve()),
    ]
    logger.info("Composing slide video …")

    result = subprocess.run(
        cmd, capture_output=True, text=True, cwd=str(output_dir.resolve()),
    )
    if result.returncode != 0:
        logger.error("ffmpeg stderr:\n%s", result.stderr)
        result.check_returncode()  # raises CalledProcessError

    logger.info("Slide video created: %s", video_path)
    return video_path


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def render_slide_video(
    script: TutorialScript,
    timing_manifest: TimingManifest,
    output_dir: Path,
    research_data: dict | None = None,
) -> Path:
    """Generate a visual-engine-driven video from script data.

    Steps:
        1. Generate keyframes via :func:`visual_engine.generate_visual_frames`
           (VS Code mock-ups, terminal views, extension panels, etc.).
        2. Screenshot every keyframe at 1920×1080 via Playwright (headless).
        3. Stitch PNGs into an H.264 MP4 with ffmpeg, timed per keyframe.

    Falls back to the legacy static-slide path when the visual engine is
    unavailable or encounters an error.

    Returns
    -------
    Path
        Path to the output ``slides_video.mp4``.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        from .visual_engine import generate_visual_frames

        logger.info("Generating interactive keyframes for '%s' …", script.topic)
        keyframes = generate_visual_frames(script, timing_manifest, research_data)

        if not keyframes:
            raise RuntimeError("Visual engine produced no keyframes")

        # Screenshot each keyframe
        image_paths, durations = _screenshot_keyframes(keyframes, output_dir)

        # Compose into video
        video_path = _compose_keyframe_video(image_paths, durations, output_dir)
        return video_path

    except Exception:
        logger.warning(
            "Visual engine failed — falling back to static slides",
            exc_info=True,
        )
        # Legacy path: static slides
        slides = _generate_slide_html(script, research_data)
        image_paths_legacy = _screenshot_slides(slides, output_dir)
        return _compose_slide_video(image_paths_legacy, timing_manifest, output_dir)
