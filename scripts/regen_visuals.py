"""Regenerate visuals and merge — reuses existing script + voice."""
import json
import logging
import shutil
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

from src.models import TutorialScript, TimingManifest
from src.slide_renderer import render_slide_video
from src.ffmpeg_helpers import merge_audio_video

base = Path(
    "outputs/2026-04-17-hypervelocity-engineering-vs-code-extension"
    "---installation,-agents,-and-ai-native-data-science-workflows"
)
script = TutorialScript.model_validate_json((base / "01_script/script.json").read_text())
timing = TimingManifest.model_validate_json((base / "02_voice/timing_manifest.json").read_text())
research = json.loads((base / "00_research/research.json").read_text())

video_path = render_slide_video(script, timing, base / "03_screen", research)
print(f"Video: {video_path}")

merged = base / "04_render/merged.mp4"
merge_audio_video(video_path, base / "02_voice/voice.wav", merged, {})
print(f"Merged: {merged}")

pub = base / "05_publish"
pub.mkdir(parents=True, exist_ok=True)
shutil.copy2(merged, pub / "tutorial.mp4")
print(f"Published: {pub / 'tutorial.mp4'}")
