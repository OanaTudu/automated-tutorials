"""Trim silence gaps from voice.wav and regenerate video for a given tutorial output."""

import json
import logging
import shutil
import subprocess
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

GAP_SEC = 1.5

if len(sys.argv) > 1:
    output_name = sys.argv[1]
else:
    output_name = "2026-04-17-hve-for-data-science"

base_voice = Path(f"outputs/{output_name}/02_voice")
base = Path(f"outputs/{output_name}")

manifest = json.loads((base_voice / "timing_manifest.json").read_text())
segments = manifest["segments"]

# 1. Extract each speech segment
seg_files: list[tuple[str, Path, float]] = []
for seg in segments:
    start_s = seg["start_ms"] / 1000.0
    dur_s = (seg["end_ms"] - seg["start_ms"]) / 1000.0
    out_file = base_voice / f"seg_{seg['id']}.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(base_voice / "voice.wav"),
         "-ss", str(start_s), "-t", str(dur_s), "-c:a", "copy", str(out_file)],
        capture_output=True, check=True,
    )
    seg_files.append((seg["id"], out_file, dur_s))
    print(f"  Extracted {seg['id']}: {dur_s:.1f}s")

# 2. Create silence gap
silence_file = base_voice / "silence.wav"
subprocess.run(
    ["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
     "-t", str(GAP_SEC), "-c:a", "pcm_s16le", str(silence_file)],
    capture_output=True, check=True,
)

# 3. Build concat list + new timing manifest
concat_lines: list[str] = []
new_segments: list[dict] = []
cursor_ms = 0

for i, (seg_id, seg_file, dur_s) in enumerate(seg_files):
    if i > 0:
        concat_lines.append(f"file '{silence_file.name}'")
        cursor_ms += int(GAP_SEC * 1000)
    concat_lines.append(f"file '{seg_file.name}'")
    start_ms = cursor_ms
    end_ms = cursor_ms + int(dur_s * 1000)
    new_segments.append({
        "id": seg_id, "start_ms": start_ms, "end_ms": end_ms,
        "text": next(s["text"] for s in segments if s["id"] == seg_id),
    })
    cursor_ms = end_ms

# 4. Concatenate
concat_path = base_voice / "concat_tight.txt"
concat_path.write_text("\n".join(concat_lines))
tight_wav = base_voice / "voice_tight.wav"
subprocess.run(
    ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
     "-i", str(concat_path.resolve()), "-c:a", "pcm_s16le", str(tight_wav.resolve())],
    capture_output=True, check=True, cwd=str(base_voice.resolve()),
)

# 5. Save new manifest + replace originals
new_manifest = {"total_duration_ms": cursor_ms, "segments": new_segments}
(base_voice / "timing_manifest.json").write_text(json.dumps(new_manifest, indent=2))
shutil.copy2(tight_wav, base_voice / "voice.wav")

# 6. Cleanup
for f in base_voice.glob("seg_*.wav"):
    f.unlink()
silence_file.unlink(missing_ok=True)
concat_path.unlink(missing_ok=True)
tight_wav.unlink(missing_ok=True)

print(f"\nTrimmed: {manifest['total_duration_ms']/1000:.1f}s -> {cursor_ms/1000:.1f}s")

# 7. Regenerate slide video with new timing
from src.models import TutorialScript, TimingManifest
from src.slide_renderer import render_slide_video
from src.ffmpeg_helpers import merge_audio_video

script = TutorialScript.model_validate_json((base / "01_script/script.json").read_text())
timing = TimingManifest.model_validate_json((base_voice / "timing_manifest.json").read_text())
research = json.loads((base / "00_research/research.json").read_text())

video_path = render_slide_video(script, timing, base / "03_screen", research)
print(f"Video: {video_path}")

merged_path = base / "04_render" / "merged.mp4"
merge_audio_video(video_path, base_voice / "voice.wav", merged_path, {})
print(f"Merged: {merged_path}")

publish_dir = base / "05_publish"
publish_dir.mkdir(parents=True, exist_ok=True)
publish_path = publish_dir / "tutorial.mp4"
shutil.copy2(merged_path, publish_path)
print(f"Published: {publish_path}")
