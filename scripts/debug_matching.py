"""Debug: trace what _extract_code_for_shot returns for each shot."""
import json
from pathlib import Path
import sys, re

sys.path.insert(0, ".")
from src.models import TutorialScript

base = Path(
    "outputs/2026-04-17-hypervelocity-engineering-vs-code-extension"
    "---installation,-agents,-and-ai-native-data-science-workflows"
)
script = TutorialScript.model_validate_json((base / "01_script/script.json").read_text())

for i, sec in enumerate(script.sections):
    title = sec.title.lower()
    print(f"\n=== Section {i}: {sec.title} ===")
    print(f"  title_lower = {repr(title)}")
    
    # Check which title rule matches
    if any(kw in title for kw in ("install", "extension", "opening")):
        print(f"  TITLE MATCH: install/extension/opening -> README welcome")
    elif any(kw in title for kw in ("plan", "implement", "model", "rpi")):
        print(f"  TITLE MATCH: plan/implement/model/rpi -> model code")
    elif any(kw in title for kw in ("agent", "meet")):
        print(f"  TITLE MATCH: agent/meet -> agent picker")
    elif any(kw in title for kw in ("research", "explore", "titanic")):
        print(f"  TITLE MATCH: research/explore/titanic")
    elif any(kw in title for kw in ("workflow", "why", "accelerate", "review", "wrap")):
        print(f"  TITLE MATCH: workflow/wrap-up -> tracking")
    else:
        print(f"  NO TITLE MATCH -> fallback")

    for j, shot in enumerate(sec.shots):
        shot_text = f"{shot.visual} {shot.action}".lower()
        fn_match = re.search(r"[\w\-]+\.\w{1,4}", shot.visual)
        fn = fn_match.group(0) if fn_match else None
        print(f"  shot {j}: filename={fn}, shot_text_snippet={shot_text[:80]}...")
