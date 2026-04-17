"""Inspect script shots to debug context matching."""
import json
from pathlib import Path

base = Path(
    "outputs/2026-04-17-hypervelocity-engineering-vs-code-extension"
    "---installation,-agents,-and-ai-native-data-science-workflows"
)
script = json.loads((base / "01_script/script.json").read_text())
for i, sec in enumerate(script["sections"]):
    print(f"\n=== Section {i}: {sec['title']} ===")
    narr = sec["narration"][:100].replace("\n", " ")
    print(f"  narration: {narr}...")
    for j, shot in enumerate(sec["shots"]):
        vis = shot["visual"][:70].replace("\n", " ")
        act = shot.get("action", "")[:60].replace("\n", " ")
        print(f"  shot{j}: visual=[{vis}]  action=[{act}]")
