"""Screen recording adapter with Playwright, OBS, and ffmpeg gdigrab modes."""

from __future__ import annotations

import json
import logging
import subprocess
import textwrap
from pathlib import Path

from .ffmpeg_helpers import normalize_video
from .models import StageResult, TimingManifest, TutorialScript

logger = logging.getLogger(__name__)


def record_demo(
    script: TutorialScript,
    output_dir: Path,
    config: dict,
) -> StageResult:
    """Record a screen demo based on the script shot list.

    Parameters
    ----------
    script:
        Tutorial script containing sections and shot list.
    output_dir:
        Directory where recording artefacts are written.
    config:
        Full pipeline config; the ``recording`` key is used for mode selection
        and capture settings.

    Returns
    -------
    StageResult:
        Stage output contract with the path to the normalised ``screen.mp4``.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    mode: str = config["recording"]["mode"]

    # Load timing manifest from voice stage output when available
    timing_manifest: TimingManifest | None = None
    manifest_path = output_dir.parent / "02_voice" / "timing_manifest.json"
    if manifest_path.exists():
        manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
        timing_manifest = TimingManifest.model_validate(manifest_data)

    if mode == "playwright":
        raw_path = _record_playwright(
            script, output_dir, config["recording"], timing_manifest=timing_manifest,
        )
    elif mode == "obs":
        raw_path = _record_obs(script, output_dir, config["recording"])
    else:
        raw_path = _record_ffmpeg(script, output_dir, config["recording"])

    # Normalize to consistent output
    final_path = output_dir / "screen.mp4"
    normalize_video(raw_path, final_path, config["recording"])

    return StageResult(stage="record", success=True, output_path=str(final_path))


# ---------------------------------------------------------------------------
# Playwright
# ---------------------------------------------------------------------------


def _shot_id(section_idx: int) -> str:
    """Map a section index to the timing-manifest segment ID convention."""
    return f"section_{section_idx}"


def _generate_demo_script(
    script: TutorialScript,
    output_path: Path,
    timing_manifest: TimingManifest | None = None,
) -> None:
    """Generate a standalone Playwright Python script that automates a browser demo.

    The generated file opens pages, types code, and demonstrates concepts from
    the tutorial shot list.  It is a best-effort template — downstream callers
    should expect rough edges and treat the recording as a starting point.

    When *timing_manifest* is provided, the generated script uses elapsed-time
    waits synchronised to the voice track instead of hardcoded shot durations.
    """
    # Build timing lookup: segment ID -> start_ms
    timing_lookup: dict[str, int] = {}
    if timing_manifest:
        timing_lookup = {seg.id: seg.start_ms for seg in timing_manifest.segments}

    use_timing = bool(timing_lookup)

    shot_blocks: list[str] = []
    if use_timing:
        shot_blocks.append("    recording_start = time.time()")

    for section_idx, section in enumerate(script.sections):
        shot_blocks.append(f"    # --- Section: {section.title} ---")
        section_start_ms = timing_lookup.get(_shot_id(section_idx))

        for shot_idx, shot in enumerate(section.shots):
            visual = shot.visual.replace("\\", "\\\\").replace('"', '\\"')

            if section_start_ms is not None and shot_idx == 0:
                # First shot in section: sync to manifest timing
                shot_blocks.append(
                    f"    elapsed_ms = (time.time() - recording_start) * 1000\n"
                    f"    remaining = max(0, {section_start_ms} - elapsed_ms)"
                )
                wait_expr = "int(remaining)"
            else:
                # Fallback: original shot-based delay
                delay_ms = int((shot.end_sec - shot.start_sec) * 1000)
                wait_expr = str(delay_ms)

            if visual.startswith(("http://", "https://")):
                shot_blocks.append(
                    f'    page.goto("{visual}")\n'
                    f'    page.wait_for_timeout({wait_expr})  # {shot.id}'
                )
            else:
                # Treat as terminal / code typing action
                shot_blocks.append(
                    f'    # visual: {visual}\n'
                    f'    page.wait_for_timeout({wait_expr})  # {shot.id}'
                )

    shots_code = "\n".join(shot_blocks)
    vw = 1280
    vh = 720
    extra_import = "\n        import time" if use_timing else ""
    # Allow callers to override defaults later via the generated file itself
    content = textwrap.dedent(f"""\
        \"\"\"Auto-generated Playwright demo script for: {script.topic}\"\"\"

        import sys{extra_import}
        from pathlib import Path
        from playwright.sync_api import sync_playwright


        def main() -> None:
            video_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=False)
                context = browser.new_context(
                    viewport={{"width": {vw}, "height": {vh}}},
                    record_video_dir=str(video_dir),
                    record_video_size={{"width": {vw}, "height": {vh}}},
                )
                page = context.new_page()

        {shots_code}

                context.close()
                browser.close()


        if __name__ == "__main__":
            main()
    """)

    output_path.write_text(content, encoding="utf-8")
    logger.info("Generated Playwright demo script at %s", output_path)


def _record_playwright(
    script: TutorialScript,
    output_dir: Path,
    cfg: dict,
    timing_manifest: TimingManifest | None = None,
) -> Path:
    """Generate and run a Playwright script that records video of the demo flow."""
    raw_path = output_dir / "raw_playwright.webm"
    demo_script = output_dir / "demo_script.py"

    _generate_demo_script(script, demo_script, timing_manifest=timing_manifest)

    result = subprocess.run(
        ["python", str(demo_script), str(output_dir)],
        capture_output=True,
        text=True,
        check=True,
        cwd=str(output_dir),
    )
    logger.info("Playwright demo output: %s", result.stdout)

    # Playwright saves video as a generated filename; grab the first webm found
    webm_files = sorted(output_dir.glob("*.webm"))
    if webm_files:
        raw_path = webm_files[0]

    return raw_path


# ---------------------------------------------------------------------------
# OBS
# ---------------------------------------------------------------------------


def _record_obs(
    script: TutorialScript,
    output_dir: Path,
    cfg: dict,
) -> Path:
    """Start OBS recording via websocket, execute demo, stop recording.

    Full OBS websocket integration is deferred (see DD-04).  For now the user
    must manually start/stop OBS so that ``raw_obs.mp4`` exists when the
    pipeline reaches this point.
    """
    raw_path = output_dir / "raw_obs.mp4"
    logger.info("OBS recording mode — requires manual setup for first run")

    if not raw_path.exists():
        raise FileNotFoundError(
            f"OBS recording not found at {raw_path}. "
            "Please start OBS manually, record the demo, and save "
            f"the output as '{raw_path.name}' in {output_dir}. "
            "Automated OBS websocket integration is deferred (DD-04)."
        )

    return raw_path


# ---------------------------------------------------------------------------
# ffmpeg gdigrab
# ---------------------------------------------------------------------------


def _record_ffmpeg(
    script: TutorialScript,
    output_dir: Path,
    cfg: dict,
) -> Path:
    """Direct desktop capture with ffmpeg gdigrab.

    When ``window_title`` is configured, captures that specific window.
    Otherwise falls back to full-desktop capture.
    """
    raw_path = output_dir / "raw_ffmpeg.mp4"
    duration = script.total_target_seconds + 10  # buffer for transitions

    window_title: str = cfg.get("window_title", "")
    capture_input = f"title={window_title}" if window_title else "desktop"

    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "gdigrab",
            "-framerate",
            str(cfg.get("fps", 30)),
            "-i",
            capture_input,
            "-t",
            str(duration),
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-pix_fmt",
            "yuv420p",
            str(raw_path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return raw_path
