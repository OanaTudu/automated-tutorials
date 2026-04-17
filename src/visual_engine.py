"""Visual engine — interpret shot descriptions and generate animated keyframe sequences.

Replaces static bullet-point slides with realistic VS Code interaction sequences.
For each shot in the tutorial script, determines what VS Code view to show, extracts
content, and generates multiple frames showing progressive actions (typing code,
running commands, viewing results).
"""

from __future__ import annotations

import html
import logging
import re
from dataclasses import dataclass
from enum import Enum

from .models import Section, Shot, TimingManifest, TutorialScript

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Scene type detection
# ---------------------------------------------------------------------------


class SceneType(Enum):
    """Visual scene categories corresponding to VS Code views."""

    EDITOR = "editor"
    TERMINAL = "terminal"
    EXTENSIONS = "extensions"
    CHAT = "chat"
    BROWSER = "browser"
    TITLE = "title"


# Ordered list of (keywords, scene_type) — first match wins.
_SCENE_RULES: list[tuple[list[str], SceneType]] = [
    (["terminal", "command", "running", "$ "], SceneType.TERMINAL),
    (["extensions", "marketplace"], SceneType.EXTENSIONS),
    (["chat", "copilot", "agent"], SceneType.CHAT),
    (["browser", "web app", "dashboard"], SceneType.BROWSER),
    (
        ["editor", "code", "vs code", "file", "script", "python", "javascript", "notebook"],
        SceneType.EDITOR,
    ),
]

_URL_RE = re.compile(r"https?://", re.IGNORECASE)
_INSTALL_EXT_RE = re.compile(r"install\b.*\b(extension|plugin)", re.IGNORECASE)
_QUOTED_CMD_RE = re.compile(r"['\"`]([^'\"` ][^'\"`]*)['\"`]")
_MARKDOWN_FENCE_RE = re.compile(r"```(?:\w+)?\n(.*?)```", re.DOTALL)


# ---------------------------------------------------------------------------
# Keyframe data structure
# ---------------------------------------------------------------------------


@dataclass
class Keyframe:
    """A single visual frame to be screenshotted."""

    html: str
    duration_ms: int
    shot_id: str
    frame_index: int


# ---------------------------------------------------------------------------
# Title / Recap / CTA slide styles (simple HTML, not VS Code mock-ups)
# ---------------------------------------------------------------------------

_SLIDE_CSS = """\
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
    content: '\\2713'; position: absolute; left: 0; color: #4ade80;
}
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
.slide-fallback {
    background: linear-gradient(160deg, #101c30 0%, #182848 100%);
}
.slide-fallback h2 {
    font-size: 48px; font-weight: 700; margin-bottom: 36px; color: #ffffff;
}
.slide-fallback ul { list-style: none; padding: 0; }
.slide-fallback ul li {
    font-size: 28px; line-height: 1.6; padding: 8px 0 8px 36px;
    position: relative; color: #c8d6e8;
}
.slide-fallback ul li::before {
    content: '\\25B8'; position: absolute; left: 0; color: #5b8dd9;
}
"""


def _esc(text: str) -> str:
    return html.escape(text, quote=True)


def _wrap_slide(body: str) -> str:
    return (
        "<!DOCTYPE html>\n<html><head><meta charset='utf-8'>"
        f"<style>{_SLIDE_CSS}</style></head><body>{body}</body></html>"
    )


# ---------------------------------------------------------------------------
# Detection helpers
# ---------------------------------------------------------------------------


def _detect_scene_type(shot: Shot) -> SceneType:
    """Determine what VS Code scene to show based on shot description."""
    combined = f"{shot.visual} {shot.action}".lower()

    # URL pattern → browser
    if _URL_RE.search(combined):
        return SceneType.BROWSER

    # "install" specifically in extension context
    if _INSTALL_EXT_RE.search(combined):
        return SceneType.EXTENSIONS

    for keywords, scene_type in _SCENE_RULES:
        if any(kw in combined for kw in keywords):
            return scene_type

    return SceneType.EDITOR


# ---------------------------------------------------------------------------
# Content extraction helpers
# ---------------------------------------------------------------------------


def _strip_fences(snippet: str) -> str:
    """Remove markdown fence markers and return bare code."""
    m = _MARKDOWN_FENCE_RE.search(snippet)
    return m.group(1).strip() if m else snippet.strip()


def _detect_language(snippet: str) -> str:
    """Best-effort language detection from a fenced code block."""
    m = re.match(r"```(\w+)", snippet)
    if m:
        return m.group(1).lower()
    if "def " in snippet or ("import " in snippet and "from " in snippet):
        return "python"
    if "function " in snippet or "const " in snippet or "=>" in snippet:
        return "javascript"
    return "unknown"


def _language_matches(lang: str, keywords: set[str]) -> bool:
    """Check if *lang* matches any of the desired language keywords."""
    py_names = {"python", "py"}
    js_names = {"javascript", "js", "jsx", "typescript", "ts", "tsx"}
    if keywords & {"python", "flask", "django", "pip"}:
        return lang in py_names
    if keywords & {"javascript", "react", "node", "usestate"}:
        return lang in js_names
    return False


def _extract_code_for_shot(
    shot: Shot,
    section: Section,
    research_data: dict | None,
) -> tuple[str, str, str]:
    """Extract ``(filename, code, language)`` for an editor shot.

    Uses the **section title** as the primary discriminator and shot-level
    keywords as a secondary signal.  This prevents narration phrases like
    "once the extension is installed" from accidentally matching the
    install-screen code in every section.
    """
    title = section.title.lower()
    shot_text = f"{shot.visual} {shot.action}".lower()

    # Try to find a filename in the visual description
    filename_match = re.search(r"[\w\-]+\.\w{1,4}", shot.visual)
    filename = filename_match.group(0) if filename_match else None

    # --- CODE SNIPPETS ----------------------------------------------------

    _WELCOME = (
        "# Welcome to your project\n"
        "#\n"
        "# Getting started:\n"
        "# 1. Open Extensions (Ctrl+Shift+X)\n"
        "# 2. Search for your extension\n"
        "# 3. Click Install\n"
        "# 4. Open the Chat panel to use AI agents"
    )

    _AGENT_PICKER = (
        "# Available HVE agents:\n"
        "#\n"
        "# @task-researcher  - Research a topic\n"
        "# @task-planner     - Create implementation plan\n"
        "# @implementer      - Write the code\n"
        "#\n"
        "# Type @ in the chat to pick an agent"
    )

    _RESEARCH_NOTES = (
        "# Titanic Dataset - Research Notes\n"
        "#\n"
        "# Key findings:\n"
        "# - 891 passengers, 12 features\n"
        "# - Survival rate: 38.4%\n"
        "# - Missing values: Age (177), Cabin (687)\n"
        "#\n"
        "# Important features:\n"
        "# - Pclass: strong correlation with survival\n"
        "# - Sex: female survival rate much higher\n"
        "# - Age: children had higher survival rate\n"
        "# - Fare: higher fare = higher survival"
    )

    _EXPLORE_TITANIC = (
        "import pandas as pd\n"
        "\n"
        "# Load the Titanic dataset\n"
        "df = pd.read_csv('titanic.csv')\n"
        "\n"
        "# Quick overview\n"
        "print(df.shape)          # (891, 12)\n"
        "print(df.head())\n"
        "\n"
        "# Check missing values\n"
        "print(df.isnull().sum())\n"
        "\n"
        "# Survival rate by class\n"
        "print(df.groupby('Pclass')['Survived'].mean())"
    )

    _MODEL_CODE = (
        "import pandas as pd\n"
        "from sklearn.linear_model import LogisticRegression\n"
        "from sklearn.model_selection import train_test_split\n"
        "\n"
        "df = pd.read_csv('titanic.csv')\n"
        "\n"
        "# Select features and target\n"
        "features = ['Pclass', 'Age', 'SibSp', 'Fare']\n"
        "X = df[features].fillna(df[features].median())\n"
        "y = df['Survived']\n"
        "\n"
        "# Split and train\n"
        "X_train, X_test, y_train, y_test = train_test_split(\n"
        "    X, y, test_size=0.2, random_state=42\n"
        ")\n"
        "model = LogisticRegression(max_iter=200)\n"
        "model.fit(X_train, y_train)\n"
        "\n"
        "# Evaluate\n"
        "score = model.score(X_test, y_test)\n"
        "print(f'Accuracy: {score:.2%}')"
    )

    _PLAN = (
        "# Implementation Plan\n"
        "#\n"
        "# Task: Build Titanic survival predictor\n"
        "#\n"
        "# Step 1: Load and explore titanic.csv\n"
        "# Step 2: Handle missing values (Age, Cabin)\n"
        "# Step 3: Select features (Pclass, Age, Fare)\n"
        "# Step 4: Train LogisticRegression model\n"
        "# Step 5: Evaluate accuracy on test set\n"
        "#\n"
        "# Expected output: ~78% accuracy"
    )

    _TRACKING = (
        "# .copilot-tracking/changes/\n"
        "#\n"
        "# Files created by HVE agents:\n"
        "#  research/titanic-research.md\n"
        "#  plans/titanic-plan.instructions.md\n"
        "#  changes/titanic_model-changes.md\n"
        "#  reviews/titanic_model-review.md\n"
        "#\n"
        "# All agent work is tracked here\n"
        "# for full auditability."
    )

    # --- SECTION-TITLE-BASED ROUTING (primary) ----------------------------

    # Section about installing extensions
    if any(kw in title for kw in ("install", "extension", "opening")):
        return filename or "README.md", _WELCOME, "python"

    # Section about planning & implementing / model building (check BEFORE agent)
    if any(kw in title for kw in ("plan", "implement", "model", "rpi")):
        if any(kw in shot_text for kw in ("plan", "switch", "agent picker")):
            return filename or "plan.md", _PLAN, "python"
        if any(kw in shot_text for kw in ("terminal", "run", "python")):
            return filename or "titanic_model.py", _MODEL_CODE, "python"
        if any(kw in shot_text for kw in ("titanic_model", "code", "paste", "editor")):
            return filename or "titanic_model.py", _MODEL_CODE, "python"
        # Default for this section: show the model code
        return filename or "titanic_model.py", _MODEL_CODE, "python"

    # Section about meeting/discovering agents
    if any(kw in title for kw in ("agent", "meet")):
        return filename or "main.py", _AGENT_PICKER, "python"

    # Section about research / exploration
    if any(kw in title for kw in ("research", "explore", "titanic")):
        if any(kw in shot_text for kw in ("tracking", "research.md", ".copilot", "folder")):
            return filename or "research_notes.md", _RESEARCH_NOTES, "python"
        if any(kw in shot_text for kw in ("editor", "content", "markdown", "scroll")):
            return filename or "research_notes.md", _RESEARCH_NOTES, "python"
        return filename or "explore_titanic.py", _EXPLORE_TITANIC, "python"

    # Section about workflow review / wrap-up / benefits
    if any(kw in title for kw in ("workflow", "why", "accelerate", "review", "wrap")):
        if any(kw in shot_text for kw in ("tracking", "copilot-tracking", "structure", "folder")):
            return filename or "changes.md", _TRACKING, "python"
        return filename or "titanic_model.py", _MODEL_CODE, "python"

    # --- SHOT-LEVEL FALLBACKS (secondary) ---------------------------------
    combined = f"{shot_text} {section.narration}".lower()

    if any(kw in combined for kw in ("install", "extension", "welcome", "marketplace")):
        return filename or "README.md", _WELCOME, "python"

    if any(kw in combined for kw in ("agent picker", "chat panel", "copilot chat")):
        return filename or "main.py", _AGENT_PICKER, "python"

    if any(kw in combined for kw in ("titanic", "explore", "dataset", "csv")):
        return filename or "explore_titanic.py", _EXPLORE_TITANIC, "python"

    if any(kw in combined for kw in ("model", "logistic", "predict", "train")):
        return filename or "titanic_model.py", _MODEL_CODE, "python"

    if any(kw in combined for kw in ("plan", "planning")):
        return filename or "plan.md", _PLAN, "python"

    if any(kw in combined for kw in ("tracking", "changes", "review")):
        return filename or "changes.md", _TRACKING, "python"

    # Fallback: search research code examples for Python
    if research_data:
        examples: list[str] = research_data.get("code_examples", [])
        for ex in examples:
            lang = _detect_language(ex)
            if lang in ("python", "py"):
                code = _strip_fences(ex)
                fn = filename or "main.py"
                return fn, code, "python"
        if examples:
            code = _strip_fences(examples[0])
            fn = filename or "main.py"
            return fn, code, "python"

    # Final fallback
    fn = filename or "main.py"
    return fn, '# TODO: code example\nprint("hello")', "python"


def _extract_terminal_content(shot: Shot, section: Section) -> tuple[str, str]:
    """Extract ``(command, output)`` for a terminal shot."""
    combined = f"{shot.visual} {shot.action}"

    # Look for quoted commands
    quoted = _QUOTED_CMD_RE.findall(combined)
    if quoted:
        command = quoted[0]
    else:
        # Look for "$ <command>" pattern
        dollar_match = re.search(r"\$\s*(.+?)(?:\s*$|['\"])", combined)
        if dollar_match:
            command = dollar_match.group(1).strip()
        elif "running" in combined.lower():
            # Extract whatever comes after "running"
            run_match = re.search(r"running\s+(.+?)(?:\s*$|[.,;])", combined, re.IGNORECASE)
            command = run_match.group(1).strip() if run_match else "python main.py"
        else:
            command = "python main.py"

    # Generate realistic output based on command
    output = _generate_terminal_output(command, section)
    return command, output


def _generate_terminal_output(command: str, section: Section) -> str:
    """Generate realistic terminal output for common commands."""
    cmd_lower = command.lower().strip()
    section_lower = section.narration.lower() if section else ""

    if cmd_lower.startswith("pip install"):
        pkg = command.split("install", 1)[-1].strip() or "package"
        return (
            f"Collecting {pkg}\n  Downloading {pkg}-1.0.0.tar.gz\n"
            f"Installing collected packages: {pkg}\n"
            f"Successfully installed {pkg}-1.0.0"
        )

    if "titanic" in cmd_lower or "titanic" in section_lower:
        if "model" in cmd_lower or "model" in section_lower or "predict" in section_lower:
            return (
                "Loading titanic.csv...\n"
                "Training LogisticRegression...\n"
                "Accuracy: 78.77%\n"
                "\n"
                "Sample predictions:\n"
                "  Passenger 1 (3rd class, age 22): Did not survive\n"
                "  Passenger 2 (1st class, age 38): Survived"
            )
        return (
            "   Survived  Pclass     Sex   Age  SibSp  Fare\n"
            "0         0       3    male  22.0      1  7.25\n"
            "1         1       1  female  38.0      1 71.28\n"
            "2         1       3  female  26.0      0  7.92\n"
            "\n"
            "Shape: (891, 12)\n"
            "Missing: Age 177, Cabin 687, Embarked 2"
        )

    if cmd_lower.startswith("python") or cmd_lower.startswith("py "):
        return "Output: OK"

    if "pytest" in cmd_lower or "test" in cmd_lower:
        return (
            "========================= test session starts "
            "=========================\ncollected 5 items\n\n"
            "tests/test_main.py .....                  [100%]\n\n"
            "========================= 5 passed in 0.12s "
            "=========================="
        )

    if cmd_lower.startswith("git "):
        return ""

    return "\u2713 Done"


def _extract_extension_content(shot: Shot, script: TutorialScript) -> dict:
    """Extract extension marketplace content from shot description."""
    combined = f"{shot.visual} {shot.action}"

    # Try to find quoted extension names
    quoted = _QUOTED_CMD_RE.findall(combined)
    search_query = quoted[0] if quoted else script.topic

    # Generate realistic extension metadata
    extensions = [
        {
            "name": search_query,
            "publisher": "Microsoft",
            "description": f"Extension for {search_query}",
            "installs": "1.2M",
            "rating": 4.8,
        },
    ]

    return {
        "search_query": search_query,
        "extensions": extensions,
        "selected_extension": extensions[0],
        "install_state": "installed" if "installed" in combined.lower() else "not_installed",
    }


def _extract_chat_content(shot: Shot, section: Section) -> list[dict[str, str]]:
    """Extract chat messages from shot description."""
    combined = f"{shot.visual} {shot.action}"

    # Look for quoted text as the user message
    quoted = _QUOTED_CMD_RE.findall(combined)
    user_msg = quoted[0] if quoted else f"Help me with {section.title.lower()}"

    messages = [{"role": "user", "content": user_msg}]

    # If the action mentions a response, add an assistant message
    if any(kw in combined.lower() for kw in ("response", "answer", "suggests", "generates")):
        messages.append({
            "role": "assistant",
            "content": f"Here's how you can approach {section.title.lower()}...",
        })

    return messages


def _extract_browser_content(shot: Shot) -> tuple[str, str, str]:
    """Extract ``(url, title, content_html)`` for a browser shot."""
    combined = f"{shot.visual} {shot.action}"

    url_match = re.search(r"(https?://[^\s\"']+)", combined)
    url = url_match.group(1) if url_match else "http://localhost:3000"

    # Derive title from URL or shot visual
    if "dashboard" in combined.lower():
        title = "Dashboard"
        content_html = "<h1>Dashboard</h1><p>Application dashboard loaded.</p>"
    elif "web app" in combined.lower():
        title = "Web Application"
        content_html = "<h1>Web Application</h1><p>Application running successfully.</p>"
    else:
        title = "Browser Preview"
        content_html = f"<h1>{_esc(shot.visual[:60])}</h1>"

    return url, title, content_html


# ---------------------------------------------------------------------------
# Fallback slide builder
# ---------------------------------------------------------------------------


def _build_fallback_slide(section: Section, shot: Shot) -> str:
    """Build a simple section slide when content extraction fails."""
    bullets = "".join(f"<li>{_esc(kp)}</li>" for kp in section.key_points)
    return _wrap_slide(
        f'<div class="slide slide-fallback">'
        f"<h2>{_esc(section.title)}</h2>"
        f"<ul>{bullets}</ul>"
        f"</div>"
    )


# ---------------------------------------------------------------------------
# Keyframe builders per scene type
# ---------------------------------------------------------------------------


def _build_editor_keyframes(
    shot: Shot,
    section: Section,
    research_data: dict | None,
) -> list[Keyframe]:
    """Generate 2-3 editor keyframes for a shot."""
    from .vscode_scenes import editor_scene

    filename, code, language = _extract_code_for_shot(shot, section, research_data)
    code_lines = code.splitlines()
    total_lines = len(code_lines)
    label = shot.on_screen_text or None

    frames: list[Keyframe] = []

    # Frame 1: partial code (typing in)
    if total_lines > 3:
        partial = "\n".join(code_lines[: total_lines // 2])
        frames.append(Keyframe(
            html=editor_scene(
                filename=filename,
                code=partial,
                language=language,
                cursor_line=total_lines // 2,
                on_screen_label=label,
            ),
            duration_ms=0,  # filled later
            shot_id=shot.id,
            frame_index=0,
        ))
    else:
        frames.append(Keyframe(
            html=editor_scene(
                filename=filename,
                code=code,
                language=language,
                cursor_line=1,
                on_screen_label=label,
            ),
            duration_ms=0,
            shot_id=shot.id,
            frame_index=0,
        ))

    # Frame 2: full code with highlighted lines
    highlight_start = max(1, total_lines - 2)
    frames.append(Keyframe(
        html=editor_scene(
            filename=filename,
            code=code,
            language=language,
            highlighted_lines=list(range(highlight_start, total_lines + 1)),
            on_screen_label=label,
        ),
        duration_ms=0,
        shot_id=shot.id,
        frame_index=len(frames),
    ))

    # Frame 3: if action mentions terminal output, show terminal panel
    action_lower = shot.action.lower()
    if any(kw in action_lower for kw in ("run", "execute", "terminal", "output")):
        _, terminal_out = _extract_terminal_content(shot, section)
        frames.append(Keyframe(
            html=editor_scene(
                filename=filename,
                code=code,
                language=language,
                highlighted_lines=list(range(highlight_start, total_lines + 1)),
                terminal_output=terminal_out,
                on_screen_label=label,
            ),
            duration_ms=0,
            shot_id=shot.id,
            frame_index=len(frames),
        ))

    return frames


def _build_terminal_keyframes(
    shot: Shot,
    section: Section,
) -> list[Keyframe]:
    """Generate 2 terminal keyframes for a shot."""
    from .vscode_scenes import terminal_scene

    command, output = _extract_terminal_content(shot, section)
    label = shot.on_screen_text or None

    frames = [
        # Frame 1: command typed
        Keyframe(
            html=terminal_scene(command=command, output="", on_screen_label=label),
            duration_ms=0,
            shot_id=shot.id,
            frame_index=0,
        ),
        # Frame 2: command output
        Keyframe(
            html=terminal_scene(command=command, output=output, on_screen_label=label),
            duration_ms=0,
            shot_id=shot.id,
            frame_index=1,
        ),
    ]
    return frames


def _build_extensions_keyframes(
    shot: Shot,
    script: TutorialScript,
) -> list[Keyframe]:
    """Generate 2-3 extensions keyframes for a shot."""
    from .vscode_scenes import extensions_scene

    ext = _extract_extension_content(shot, script)
    label = shot.on_screen_text or None

    frames = [
        # Frame 1: search query typed
        Keyframe(
            html=extensions_scene(
                search_query=ext["search_query"],
                on_screen_label=label,
            ),
            duration_ms=0,
            shot_id=shot.id,
            frame_index=0,
        ),
        # Frame 2: search results
        Keyframe(
            html=extensions_scene(
                search_query=ext["search_query"],
                extensions=ext["extensions"],
                on_screen_label=label,
            ),
            duration_ms=0,
            shot_id=shot.id,
            frame_index=1,
        ),
        # Frame 3: detail panel with install state
        Keyframe(
            html=extensions_scene(
                search_query=ext["search_query"],
                extensions=ext["extensions"],
                selected_extension=ext["selected_extension"],
                install_state=ext["install_state"],
                on_screen_label=label,
            ),
            duration_ms=0,
            shot_id=shot.id,
            frame_index=2,
        ),
    ]
    return frames


def _build_chat_keyframes(
    shot: Shot,
    section: Section,
) -> list[Keyframe]:
    """Generate 2 chat keyframes for a shot."""
    from .vscode_scenes import chat_scene

    messages = _extract_chat_content(shot, section)
    label = shot.on_screen_text or None

    frames = [
        # Frame 1: user message typed
        Keyframe(
            html=chat_scene(messages=messages[:1], on_screen_label=label),
            duration_ms=0,
            shot_id=shot.id,
            frame_index=0,
        ),
    ]

    # Frame 2: assistant response (if available)
    if len(messages) > 1:
        frames.append(Keyframe(
            html=chat_scene(messages=messages, on_screen_label=label),
            duration_ms=0,
            shot_id=shot.id,
            frame_index=1,
        ))
    else:
        # Show with input text to indicate waiting
        frames.append(Keyframe(
            html=chat_scene(
                messages=messages,
                input_text="...",
                on_screen_label=label,
            ),
            duration_ms=0,
            shot_id=shot.id,
            frame_index=1,
        ))

    return frames


def _build_browser_keyframes(shot: Shot) -> list[Keyframe]:
    """Generate 2 browser keyframes for a shot."""
    from .vscode_scenes import browser_scene

    url, title, content_html = _extract_browser_content(shot)
    label = shot.on_screen_text or None

    frames = [
        # Frame 1: URL in address bar, loading
        Keyframe(
            html=browser_scene(url=url, title=title, content_html="", on_screen_label=label),
            duration_ms=0,
            shot_id=shot.id,
            frame_index=0,
        ),
        # Frame 2: page loaded
        Keyframe(
            html=browser_scene(
                url=url,
                title=title,
                content_html=content_html,
                on_screen_label=label,
            ),
            duration_ms=0,
            shot_id=shot.id,
            frame_index=1,
        ),
    ]
    return frames


# ---------------------------------------------------------------------------
# Shot → keyframes dispatcher
# ---------------------------------------------------------------------------


def _build_keyframes_for_shot(
    shot: Shot,
    section: Section,
    scene_type: SceneType,
    research_data: dict | None,
    script: TutorialScript,
) -> list[Keyframe]:
    """Generate 2-4 keyframes using the unified IDE layout.

    Every keyframe shows the full VS Code IDE (editor + terminal + chat +
    sidebar) with the *focus* panel highlighted and its content matching
    the shot description.
    """
    from .vscode_scenes import full_ide_scene

    try:
        label = shot.on_screen_text or None

        # --- Determine content for each panel based on scene type ----------
        filename, code, language = _extract_code_for_shot(shot, section, research_data)
        command, output = _extract_terminal_content(shot, section)
        chat_msgs = _extract_chat_content(shot, section)

        # Context-aware explorer files (section-title driven)
        title_lower = section.title.lower()
        if any(kw in title_lower for kw in ("install", "extension", "opening")):
            project_files = ["README.md", "requirements.txt"]
        elif any(kw in title_lower for kw in ("plan", "implement", "model", "rpi")):
            project_files = [
                "titanic.csv",
                "explore_titanic.py",
                filename,
                ".copilot-tracking/",
                "  plans/",
                "  changes/",
            ]
        elif any(kw in title_lower for kw in ("agent", "meet")):
            project_files = ["README.md", filename, "requirements.txt"]
        elif any(kw in title_lower for kw in ("research", "explore", "titanic")):
            project_files = [
                "titanic.csv",
                filename,
                ".copilot-tracking/",
                "  research/",
            ]
        elif any(kw in title_lower for kw in ("workflow", "why", "accelerate", "review")):
            project_files = [
                "titanic.csv",
                "explore_titanic.py",
                "titanic_model.py",
                ".copilot-tracking/",
                "  research/",
                "  plans/",
                "  changes/",
            ]
        else:
            project_files = ["README.md", filename, "requirements.txt"]

        # Common kwargs shared across all frames
        base_kwargs: dict = {
            "editor_filename": filename,
            "editor_language": language,
            "explorer_files": project_files,
            "on_screen_label": label,
        }

        frames: list[Keyframe] = []

        if scene_type == SceneType.EXTENSIONS:
            ext = _extract_extension_content(shot, script)
            # Frame 1: open extensions sidebar, search
            frames.append(Keyframe(
                html=full_ide_scene(
                    focus="extensions",
                    sidebar_mode="extensions",
                    ext_search_query=ext["search_query"],
                    extensions_list=ext["extensions"],
                    ext_install_state="install",
                    editor_code=code,
                    terminal_lines=f"$ # Ready to install {ext['search_query']}",
                    chat_messages=[],
                    **base_kwargs,
                ),
                duration_ms=0, shot_id=shot.id, frame_index=0,
            ))
            # Frame 2: extension installed
            frames.append(Keyframe(
                html=full_ide_scene(
                    focus="extensions",
                    sidebar_mode="extensions",
                    ext_search_query=ext["search_query"],
                    extensions_list=ext["extensions"],
                    ext_install_state="installed",
                    editor_code=code,
                    terminal_lines=f"Extension '{ext['search_query']}' is now active.",
                    chat_messages=[{"role": "assistant", "content": f"✓ {ext['search_query']} extension is ready!"}],
                    **base_kwargs,
                ),
                duration_ms=0, shot_id=shot.id, frame_index=1,
            ))

        elif scene_type == SceneType.CHAT:
            # Frame 1: user types message in chat
            frames.append(Keyframe(
                html=full_ide_scene(
                    focus="chat",
                    editor_code=code,
                    terminal_lines="$ ",
                    chat_messages=chat_msgs[:1],
                    chat_input=chat_msgs[0]["content"] if chat_msgs else "",
                    **base_kwargs,
                ),
                duration_ms=0, shot_id=shot.id, frame_index=0,
            ))
            # Frame 2: assistant responds
            full_msgs = chat_msgs if len(chat_msgs) > 1 else chat_msgs + [
                {"role": "assistant", "content": f"Here's how to approach {section.title.lower()}..."}
            ]
            frames.append(Keyframe(
                html=full_ide_scene(
                    focus="chat",
                    editor_code=code,
                    terminal_lines="$ ",
                    chat_messages=full_msgs,
                    **base_kwargs,
                ),
                duration_ms=0, shot_id=shot.id, frame_index=1,
            ))

        elif scene_type == SceneType.TERMINAL:
            # Frame 1: command typed
            frames.append(Keyframe(
                html=full_ide_scene(
                    focus="terminal",
                    editor_code=code,
                    terminal_lines=f"$ {command}",
                    chat_messages=[],
                    **base_kwargs,
                ),
                duration_ms=0, shot_id=shot.id, frame_index=0,
            ))
            # Frame 2: command output
            frames.append(Keyframe(
                html=full_ide_scene(
                    focus="terminal",
                    editor_code=code,
                    terminal_lines=f"$ {command}\n{output}",
                    chat_messages=[],
                    **base_kwargs,
                ),
                duration_ms=0, shot_id=shot.id, frame_index=1,
            ))

        elif scene_type == SceneType.EDITOR:
            code_lines = code.splitlines()
            total_lines = len(code_lines)
            # Frame 1: partial code (typing)
            if total_lines > 3:
                partial = "\n".join(code_lines[: total_lines // 2])
                frames.append(Keyframe(
                    html=full_ide_scene(
                        focus="editor",
                        editor_code=partial,
                        editor_cursor_line=total_lines // 2,
                        terminal_lines="$ ",
                        chat_messages=[],
                        **base_kwargs,
                    ),
                    duration_ms=0, shot_id=shot.id, frame_index=0,
                ))
            # Frame 2: full code with highlights
            hl_start = max(1, total_lines - 2)
            frames.append(Keyframe(
                html=full_ide_scene(
                    focus="editor",
                    editor_code=code,
                    editor_highlighted_lines=list(range(hl_start, total_lines + 1)),
                    terminal_lines="$ ",
                    chat_messages=[],
                    **base_kwargs,
                ),
                duration_ms=0, shot_id=shot.id, frame_index=len(frames),
            ))
            # Frame 3: if action mentions run/output, show terminal with result
            action_lower = shot.action.lower()
            if any(kw in action_lower for kw in ("run", "execute", "terminal", "output")):
                frames.append(Keyframe(
                    html=full_ide_scene(
                        focus="terminal",
                        editor_code=code,
                        editor_highlighted_lines=list(range(hl_start, total_lines + 1)),
                        terminal_lines=f"$ {command}\n{output}",
                        chat_messages=[],
                        **base_kwargs,
                    ),
                    duration_ms=0, shot_id=shot.id, frame_index=len(frames),
                ))

        elif scene_type == SceneType.BROWSER:
            url, title, content_html = _extract_browser_content(shot)
            # For browser scenes, show a chat message pointing to the URL
            frames.append(Keyframe(
                html=full_ide_scene(
                    focus="editor",
                    editor_code=f"# Open: {url}\n# {title}\n\n{code}",
                    terminal_lines=f"$ # Navigate to {url}",
                    chat_messages=[{"role": "assistant", "content": f"Opening {url}..."}],
                    **base_kwargs,
                ),
                duration_ms=0, shot_id=shot.id, frame_index=0,
            ))
            frames.append(Keyframe(
                html=full_ide_scene(
                    focus="editor",
                    editor_code=f"# {title}\n# {url}\n\n{code}",
                    terminal_lines=f"$ # {title} loaded successfully",
                    chat_messages=[{"role": "assistant", "content": f"✓ {title} is ready."}],
                    **base_kwargs,
                ),
                duration_ms=0, shot_id=shot.id, frame_index=1,
            ))

        if not frames:
            # Fallback: show IDE with section info in editor
            frames.append(Keyframe(
                html=full_ide_scene(
                    focus="editor",
                    editor_code=f"# {section.title}\n# " + "\n# ".join(section.key_points),
                    terminal_lines="$ ",
                    chat_messages=[],
                    **base_kwargs,
                ),
                duration_ms=0, shot_id=shot.id, frame_index=0,
            ))

        return frames

    except Exception:
        logger.warning(
            "Failed to build unified IDE keyframes for shot %s — falling back",
            shot.id,
            exc_info=True,
        )

    # Fallback for TITLE or any error
    return [Keyframe(
        html=_build_fallback_slide(section, shot),
        duration_ms=0,
        shot_id=shot.id,
        frame_index=0,
    )]


# ---------------------------------------------------------------------------
# Title / Recap / CTA frame builders
# ---------------------------------------------------------------------------


def _build_title_frame(script: TutorialScript, duration_ms: int) -> Keyframe:
    """Build the opening title keyframe."""
    body = (
        f'<div class="slide slide-title">'
        f"<h1>{_esc(script.topic)}</h1>"
        f'<div class="subtitle">A tutorial for {_esc(script.audience)}</div>'
        f"</div>"
    )
    return Keyframe(
        html=_wrap_slide(body),
        duration_ms=duration_ms,
        shot_id="hook",
        frame_index=0,
    )


def _build_recap_frame(script: TutorialScript, duration_ms: int) -> Keyframe:
    """Build the recap keyframe."""
    items = "".join(f"<li>{_esc(s.title)}</li>" for s in script.sections)
    body = (
        f'<div class="slide slide-recap">'
        f"<h2>Recap</h2>"
        f"<ul>{items}</ul>"
        f"</div>"
    )
    return Keyframe(
        html=_wrap_slide(body),
        duration_ms=duration_ms,
        shot_id="recap",
        frame_index=0,
    )


def _build_cta_frame(script: TutorialScript, duration_ms: int) -> Keyframe:
    """Build the call-to-action keyframe."""
    body = (
        f'<div class="slide slide-cta">'
        f"<h2>Thanks for watching!</h2>"
        f"<p>{_esc(script.cta)}</p>"
        f"</div>"
    )
    return Keyframe(
        html=_wrap_slide(body),
        duration_ms=duration_ms,
        shot_id="cta",
        frame_index=0,
    )


# ---------------------------------------------------------------------------
# Timing helpers
# ---------------------------------------------------------------------------


def _segment_duration_ms(manifest: TimingManifest, seg_id: str) -> int:
    """Get the duration for a timing segment by its id."""
    for i, seg in enumerate(manifest.segments):
        if seg.id == seg_id:
            return manifest.slot_duration_ms(i)
    return 3000  # safe default


def _distribute_duration(total_ms: int, count: int) -> list[int]:
    """Evenly split *total_ms* across *count* keyframes, absorbing remainder in the last."""
    if count <= 0:
        return []
    base = total_ms // count
    durations = [base] * count
    durations[-1] += total_ms - base * count
    return durations


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_visual_frames(
    script: TutorialScript,
    timing_manifest: TimingManifest,
    research_data: dict | None = None,
) -> list[Keyframe]:
    """Generate all keyframes for the tutorial video.

    Returns an ordered list of :class:`Keyframe` objects. Each keyframe has HTML
    content and a duration in milliseconds. The total duration of all keyframes
    matches the timing manifest.

    Includes a title frame (for the hook segment), section frames (for each
    shot), a recap frame, and a CTA frame.
    """
    frames: list[Keyframe] = []

    # 1. Title frame for the "hook" segment
    hook_ms = _segment_duration_ms(timing_manifest, "hook")
    frames.append(_build_title_frame(script, hook_ms))

    # 2. Section frames — one set of keyframes per shot
    for sec_idx, section in enumerate(script.sections):
        seg_id = f"section_{sec_idx}"
        section_ms = _segment_duration_ms(timing_manifest, seg_id)

        if not section.shots:
            # No shots: single fallback slide for the whole section
            fallback_shot = Shot(
                id=f"{seg_id}_fallback",
                start_sec=0,
                end_sec=1,
                visual=section.title,
                action="display",
            )
            frames.append(Keyframe(
                html=_build_fallback_slide(section, fallback_shot),
                duration_ms=section_ms,
                shot_id=fallback_shot.id,
                frame_index=0,
            ))
            continue

        # Divide section time across shots proportionally by their duration
        shot_durations = []
        total_shot_sec = sum(s.end_sec - s.start_sec for s in section.shots)
        for shot in section.shots:
            shot_sec = shot.end_sec - shot.start_sec
            if total_shot_sec > 0:
                shot_ms = int(section_ms * shot_sec / total_shot_sec)
            else:
                shot_ms = section_ms // len(section.shots)
            shot_durations.append(shot_ms)

        # Absorb rounding error into the last shot
        leftover = section_ms - sum(shot_durations)
        if shot_durations:
            shot_durations[-1] += leftover

        for shot, shot_ms in zip(section.shots, shot_durations):
            scene = _detect_scene_type(shot)
            keyframes = _build_keyframes_for_shot(
                shot, section, scene, research_data, script,
            )

            if not keyframes:
                keyframes = [Keyframe(
                    html=_build_fallback_slide(section, shot),
                    duration_ms=shot_ms,
                    shot_id=shot.id,
                    frame_index=0,
                )]
            else:
                # Distribute this shot's time across its keyframes
                durations = _distribute_duration(shot_ms, len(keyframes))
                for kf, dur in zip(keyframes, durations):
                    kf.duration_ms = dur

            frames.extend(keyframes)

    # 3. Recap frame
    recap_ms = _segment_duration_ms(timing_manifest, "recap")
    frames.append(_build_recap_frame(script, recap_ms))

    # 4. CTA frame
    cta_ms = _segment_duration_ms(timing_manifest, "cta")
    frames.append(_build_cta_frame(script, cta_ms))

    logger.info(
        "Generated %d keyframes for '%s' (total %d ms)",
        len(frames),
        script.topic,
        sum(f.duration_ms for f in frames),
    )
    return frames
