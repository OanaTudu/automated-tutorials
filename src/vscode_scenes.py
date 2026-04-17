"""Generate pixel-perfect VS Code dark-theme HTML mock-ups for tutorial video frames.

Each public function returns a complete HTML string (DOCTYPE through </html>) that,
when rendered at 1920×1080 in Playwright, looks like a real VS Code screenshot.
"""

from __future__ import annotations

import html
import re

# ---------------------------------------------------------------------------
# Colour palette  (VS Code Dark+ theme)
# ---------------------------------------------------------------------------
_BG_EDITOR = "#1e1e1e"
_BG_SIDEBAR = "#252526"
_BG_ACTIVITY = "#181818"
_BG_STATUSBAR = "#007acc"
_BG_TITLEBAR = "#323233"
_BG_TAB_ACTIVE = "#1e1e1e"
_BG_TAB_INACTIVE = "#2d2d2d"
_BG_TERMINAL = "#1e1e1e"
_BG_INPUT = "#3c3c3c"

_FG_DEFAULT = "#d4d4d4"
_FG_KEYWORD = "#569cd6"
_FG_STRING = "#ce9178"
_FG_COMMENT = "#6a9955"
_FG_TYPE = "#4ec9b0"
_FG_FUNCTION = "#dcdcaa"
_FG_NUMBER = "#b5cea8"
_FG_LINENO = "#858585"
_FG_DIM = "#858585"

_FONT_CODE = "'Cascadia Code', 'Consolas', 'Courier New', monospace"
_FONT_UI = "'Segoe UI', system-ui, sans-serif"

_HIGHLIGHT_BG = "rgba(255, 255, 0, 0.07)"

# Activity bar icons (Unicode placeholders)
_ACTIVITY_ICONS: list[tuple[str, str]] = [
    ("files", "📄"),
    ("search", "🔍"),
    ("extensions", "🧩"),
    ("run", "▶"),
    ("chat", "💬"),
]


# ---------------------------------------------------------------------------
# Shared CSS (injected once per page via _wrap_page)
# ---------------------------------------------------------------------------
def _shared_css() -> str:
    """Return the shared CSS block used by every scene."""
    return f"""
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
        width: 1920px; height: 1080px; margin: 0; overflow: hidden;
        background: {_BG_EDITOR}; color: {_FG_DEFAULT};
        font-family: {_FONT_UI}; font-size: 13px;
        display: flex; flex-direction: column;
    }}
    .main-row {{ display: flex; flex: 1; min-height: 0; }}

    /* Activity bar */
    .activity-bar {{
        width: 48px; background: {_BG_ACTIVITY};
        display: flex; flex-direction: column; align-items: center;
        padding-top: 8px; flex-shrink: 0;
    }}
    .activity-bar .icon {{
        width: 48px; height: 48px; display: flex;
        align-items: center; justify-content: center;
        font-size: 20px; cursor: default; border-left: 2px solid transparent;
    }}
    .activity-bar .icon.active {{
        border-left-color: {_FG_DEFAULT}; color: {_FG_DEFAULT};
    }}
    .activity-bar .icon:not(.active) {{ opacity: 0.5; }}

    /* Sidebar */
    .sidebar {{
        width: 240px; background: {_BG_SIDEBAR};
        flex-shrink: 0; display: flex; flex-direction: column;
        font-size: 13px; overflow: hidden;
    }}
    .sidebar-header {{
        padding: 10px 12px; text-transform: uppercase; font-size: 11px;
        font-weight: 600; letter-spacing: 0.5px; color: {_FG_DIM};
    }}
    .sidebar-file {{
        padding: 3px 12px 3px 24px; cursor: default;
        white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    }}
    .sidebar-file:hover {{ background: rgba(255,255,255,0.05); }}

    /* Tab bar */
    .tab-bar {{
        height: 35px; background: {_BG_TITLEBAR};
        display: flex; align-items: stretch; flex-shrink: 0;
    }}
    .tab {{
        padding: 0 16px; display: flex; align-items: center; gap: 6px;
        font-size: 13px; cursor: default; border-right: 1px solid #1e1e1e;
        background: {_BG_TAB_INACTIVE}; color: {_FG_DIM};
    }}
    .tab.active {{
        background: {_BG_TAB_ACTIVE}; color: {_FG_DEFAULT};
        border-bottom: 1px solid {_BG_TAB_ACTIVE};
    }}
    .tab .close {{ font-size: 14px; opacity: 0.5; margin-left: 4px; }}

    /* Editor area */
    .editor-area {{
        flex: 1; display: flex; flex-direction: column; min-width: 0;
    }}
    .editor-content {{
        flex: 1; display: flex; overflow: hidden; position: relative;
    }}
    .line-numbers {{
        padding: 4px 12px 4px 16px; text-align: right;
        color: {_FG_LINENO}; font-family: {_FONT_CODE}; font-size: 14px;
        line-height: 20px; user-select: none; flex-shrink: 0;
        white-space: pre;
    }}
    .code-area {{
        flex: 1; padding: 4px 0 4px 8px; font-family: {_FONT_CODE};
        font-size: 14px; line-height: 20px; overflow: hidden;
        white-space: pre; min-width: 0;
    }}
    .code-line {{ height: 20px; padding-right: 16px; }}
    .code-line.highlighted {{ background: {_HIGHLIGHT_BG}; }}
    .cursor {{
        display: inline-block; width: 2px; height: 18px;
        background: {_FG_DEFAULT}; vertical-align: text-bottom;
        animation: blink 1s step-end infinite;
    }}
    @keyframes blink {{
        50% {{ opacity: 0; }}
    }}

    /* Minimap */
    .minimap {{
        width: 60px; flex-shrink: 0;
        background: linear-gradient(
            180deg,
            rgba(255,255,255,0.04) 0%,
            rgba(255,255,255,0.02) 40%,
            rgba(255,255,255,0.01) 100%
        );
    }}

    /* Terminal */
    .terminal-panel {{
        height: 200px; background: {_BG_TERMINAL};
        border-top: 1px solid #333; display: flex; flex-direction: column;
        flex-shrink: 0;
    }}
    .terminal-header {{
        height: 30px; padding: 0 12px; display: flex; align-items: center;
        font-size: 11px; text-transform: uppercase; color: {_FG_DIM};
        border-bottom: 1px solid #333; letter-spacing: 0.5px;
    }}
    .terminal-body {{
        flex: 1; padding: 8px 16px; font-family: {_FONT_CODE};
        font-size: 13px; line-height: 18px; overflow: hidden;
        white-space: pre; color: {_FG_DEFAULT};
    }}

    /* Status bar */
    .status-bar {{
        height: 22px; background: {_BG_STATUSBAR};
        display: flex; align-items: center; justify-content: space-between;
        padding: 0 12px; font-size: 12px; color: #fff; flex-shrink: 0;
    }}
    .status-left, .status-right {{
        display: flex; gap: 16px; align-items: center;
    }}
    .status-item {{ white-space: nowrap; }}

    /* Floating label */
    .on-screen-label {{
        position: fixed; bottom: 40px; right: 24px;
        background: rgba(0,0,0,0.72); color: #fff;
        padding: 8px 18px; border-radius: 6px; font-size: 15px;
        font-family: {_FONT_UI}; pointer-events: none;
        z-index: 9999;
    }}
    """


# ---------------------------------------------------------------------------
# Internal helper components
# ---------------------------------------------------------------------------
def _activity_bar(active_icon: str = "files") -> str:
    """Return HTML for the VS Code activity bar.

    Parameters
    ----------
    active_icon:
        Which icon is highlighted: ``"files"``, ``"search"``,
        ``"extensions"``, ``"run"``, or ``"chat"``.
    """
    icons_html: list[str] = []
    for key, emoji in _ACTIVITY_ICONS:
        cls = "icon active" if key == active_icon else "icon"
        icons_html.append(f'<div class="{cls}">{emoji}</div>')
    return '<div class="activity-bar">' + "\n".join(icons_html) + "</div>"


def _status_bar(items: dict[str, str | None]) -> str:
    """Return HTML for the VS Code status bar.

    Parameters
    ----------
    items:
        Mapping of position keys (``"branch"``, ``"language"``, ``"encoding"``,
        ``"eol"``, ``"indent"``, ``"position"``) to display strings.
        ``None`` values are skipped.
    """
    left_keys = ["branch"]
    right_keys = ["language", "encoding", "eol", "indent", "position"]

    left = "".join(
        f'<span class="status-item">● {v}</span>'
        if k == "branch"
        else f'<span class="status-item">{v}</span>'
        for k in left_keys
        if (v := items.get(k))
    )
    right = "".join(
        f'<span class="status-item">{v}</span>'
        for k in right_keys
        if (v := items.get(k))
    )
    return (
        '<div class="status-bar">'
        f'<div class="status-left">{left}</div>'
        f'<div class="status-right">{right}</div>'
        "</div>"
    )


def _tab_bar(tabs: list[str], active_tab: str) -> str:
    """Return HTML for the editor tab bar.

    Parameters
    ----------
    tabs:
        List of filenames to show as tabs.
    active_tab:
        The tab that should appear selected.
    """
    parts: list[str] = []
    for t in tabs:
        cls = "tab active" if t == active_tab else "tab"
        parts.append(f'<div class="{cls}">{_esc(t)}<span class="close">×</span></div>')
    return '<div class="tab-bar">' + "".join(parts) + "</div>"


def _wrap_page(body_html: str, extra_css: str = "") -> str:
    """Wrap *body_html* in a full HTML document with shared CSS.

    Parameters
    ----------
    body_html:
        Inner HTML to place inside ``<body>``.
    extra_css:
        Additional CSS rules appended after the shared block.
    """
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n<head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=1920,height=1080">\n'
        f"<style>{_shared_css()}{extra_css}</style>\n"
        "</head>\n"
        f"<body>\n{body_html}\n</body>\n</html>"
    )


def _esc(text: str) -> str:
    """HTML-escape *text*."""
    return html.escape(text, quote=True)


def _on_screen_label_html(label: str | None) -> str:
    if label is None:
        return ""
    return f'<div class="on-screen-label">{_esc(label)}</div>'


# ---------------------------------------------------------------------------
# Syntax highlighting helpers
# ---------------------------------------------------------------------------
_PY_KEYWORDS = {
    "def", "class", "import", "from", "return", "if", "elif", "else",
    "for", "while", "with", "as", "try", "except", "raise",
    "True", "False", "None", "self", "async", "await",
}

_JS_KEYWORDS = {
    "function", "const", "let", "var", "return", "if", "else", "for",
    "import", "export", "default", "from", "async", "await", "new",
    "this", "class",
}


def _highlight_python(line: str) -> str:
    """Apply Python syntax highlighting spans to a single *line*."""
    # Already HTML-escaped below; we escape pieces as we go.
    result: list[str] = []
    i = 0
    n = len(line)
    while i < n:
        # Comments
        if line[i] == "#":
            result.append(f'<span style="color:{_FG_COMMENT}">{_esc(line[i:])}</span>')
            break
        # Strings (triple or single/double)
        if line[i] in ('"', "'"):
            quote = line[i]
            triple = line[i : i + 3] in ('"""', "'''")
            end_pat = quote * 3 if triple else quote
            start = i
            i += 3 if triple else 1
            while i < n:
                if line[i] == "\\" and i + 1 < n:
                    i += 2
                    continue
                if line[i:].startswith(end_pat):
                    i += len(end_pat)
                    break
                i += 1
            else:
                i = n
            result.append(
                f'<span style="color:{_FG_STRING}">{_esc(line[start:i])}</span>'
            )
            continue
        # Decorators
        if line[i] == "@" and (i == 0 or line[i - 1] in (" ", "\t")):
            m = re.match(r"@[\w.]+", line[i:])
            if m:
                result.append(
                    f'<span style="color:{_FG_FUNCTION}">{_esc(m.group())}</span>'
                )
                i += len(m.group())
                continue
        # Numbers
        if line[i].isdigit() and (i == 0 or not line[i - 1].isalnum()):
            m = re.match(r"\d[\d_.]*", line[i:])
            if m:
                result.append(
                    f'<span style="color:{_FG_NUMBER}">{_esc(m.group())}</span>'
                )
                i += len(m.group())
                continue
        # Words (keywords, function calls, identifiers)
        if line[i].isalpha() or line[i] == "_":
            m = re.match(r"[A-Za-z_]\w*", line[i:])
            if m:
                word = m.group()
                end_idx = i + len(word)
                if word in _PY_KEYWORDS:
                    result.append(
                        f'<span style="color:{_FG_KEYWORD}">{_esc(word)}</span>'
                    )
                elif end_idx < n and line[end_idx] == "(":
                    result.append(
                        f'<span style="color:{_FG_FUNCTION}">{_esc(word)}</span>'
                    )
                else:
                    result.append(_esc(word))
                i = end_idx
                continue
        result.append(_esc(line[i]))
        i += 1
    return "".join(result)


def _highlight_js(line: str) -> str:
    """Apply JavaScript/TypeScript syntax highlighting to a single *line*."""
    result: list[str] = []
    i = 0
    n = len(line)
    while i < n:
        # Single-line comment
        if line[i : i + 2] == "//":
            result.append(f'<span style="color:{_FG_COMMENT}">{_esc(line[i:])}</span>')
            break
        # Strings
        if line[i] in ('"', "'", "`"):
            quote = line[i]
            start = i
            i += 1
            while i < n:
                if line[i] == "\\" and i + 1 < n:
                    i += 2
                    continue
                if line[i] == quote:
                    i += 1
                    break
                i += 1
            else:
                i = n
            result.append(
                f'<span style="color:{_FG_STRING}">{_esc(line[start:i])}</span>'
            )
            continue
        # Arrow function
        if line[i : i + 2] == "=>":
            result.append(f'<span style="color:{_FG_KEYWORD}">=&gt;</span>')
            i += 2
            continue
        # Numbers
        if line[i].isdigit() and (i == 0 or not line[i - 1].isalnum()):
            m = re.match(r"\d[\d_.]*", line[i:])
            if m:
                result.append(
                    f'<span style="color:{_FG_NUMBER}">{_esc(m.group())}</span>'
                )
                i += len(m.group())
                continue
        # Words
        if line[i].isalpha() or line[i] == "_":
            m = re.match(r"[A-Za-z_]\w*", line[i:])
            if m:
                word = m.group()
                end_idx = i + len(word)
                if word in _JS_KEYWORDS:
                    result.append(
                        f'<span style="color:{_FG_KEYWORD}">{_esc(word)}</span>'
                    )
                elif end_idx < n and line[end_idx] == "(":
                    result.append(
                        f'<span style="color:{_FG_FUNCTION}">{_esc(word)}</span>'
                    )
                else:
                    result.append(_esc(word))
                i = end_idx
                continue
        result.append(_esc(line[i]))
        i += 1
    return "".join(result)


def _highlight_yaml(line: str) -> str:
    """Apply YAML syntax highlighting to a single *line*."""
    stripped = line.lstrip()
    # Comment line
    if stripped.startswith("#"):
        return f'<span style="color:{_FG_COMMENT}">{_esc(line)}</span>'
    # Key: value
    m = re.match(r"^(\s*)([\w][\w.-]*)(:)(.*)", line)
    if m:
        indent, key, colon, rest = m.group(1), m.group(2), m.group(3), m.group(4)
        rest_html = _esc(rest)
        # Inline comment after value
        cm = re.search(r"(#.*)$", rest)
        if cm:
            before = rest[: cm.start()]
            comment = cm.group(1)
            rest_html = _esc(before) + f'<span style="color:{_FG_COMMENT}">{_esc(comment)}</span>'
        # Colour boolean / null values
        for kw in ("true", "false", "null"):
            rest_html = rest_html.replace(
                kw, f'<span style="color:{_FG_KEYWORD}">{kw}</span>'
            )
        # Colour quoted strings
        rest_html = re.sub(
            r'(&quot;.*?&quot;|&#x27;.*?&#x27;)',
            rf'<span style="color:{_FG_STRING}">\1</span>',
            rest_html,
        )
        return (
            f'{_esc(indent)}'
            f'<span style="color:{_FG_KEYWORD}">{_esc(key)}</span>'
            f'{_esc(colon)}{rest_html}'
        )
    return _esc(line)


def _highlight_code(code: str, language: str) -> list[str]:
    """Return a list of HTML strings, one per source line, with syntax spans.

    Parameters
    ----------
    code:
        The raw source code.
    language:
        ``"python"``, ``"javascript"``, ``"typescript"``, ``"yaml"``, etc.
    """
    lang = language.lower()
    highlighter = {
        "python": _highlight_python,
        "javascript": _highlight_js,
        "typescript": _highlight_js,
        "js": _highlight_js,
        "ts": _highlight_js,
        "yaml": _highlight_yaml,
        "yml": _highlight_yaml,
    }.get(lang)

    lines = code.split("\n")
    if highlighter:
        return [highlighter(ln) for ln in lines]
    return [_esc(ln) for ln in lines]


# ---------------------------------------------------------------------------
# Scene 1 – Editor
# ---------------------------------------------------------------------------
def editor_scene(
    filename: str,
    code: str,
    language: str,
    highlighted_lines: list[int] | None = None,
    cursor_line: int | None = None,
    sidebar_files: list[str] | None = None,
    terminal_output: str | None = None,
    on_screen_label: str | None = None,
) -> str:
    """Return an HTML page showing VS Code with *code* open in the editor.

    Parameters
    ----------
    filename:
        File name shown in the active tab and sidebar explorer.
    code:
        Source code displayed in the editor pane.
    language:
        Programming language (used for syntax highlighting).
    highlighted_lines:
        1-based line numbers that receive a yellow highlight.
    cursor_line:
        1-based line number where a blinking cursor is shown.
    sidebar_files:
        File list for the explorer panel (defaults to ``[filename]``).
    terminal_output:
        If provided, a terminal panel appears at the bottom.
    on_screen_label:
        Optional floating label in the lower-right corner.
    """
    hl_set = set(highlighted_lines or [])
    files = sidebar_files or [filename]
    highlighted = _highlight_code(code, language)
    total_lines = len(highlighted)

    # Line numbers
    lineno_html = "\n".join(str(i) for i in range(1, total_lines + 1))

    # Code lines
    code_lines: list[str] = []
    for idx, line_html in enumerate(highlighted, start=1):
        cls = "code-line highlighted" if idx in hl_set else "code-line"
        cursor = '<span class="cursor"></span>' if idx == cursor_line else ""
        code_lines.append(f'<div class="{cls}">{line_html}{cursor}</div>')

    # Sidebar files
    file_items = "\n".join(
        f'<div class="sidebar-file">{_esc(f)}</div>' for f in files
    )

    # Terminal
    terminal_html = ""
    if terminal_output is not None:
        terminal_html = (
            '<div class="terminal-panel">'
            '<div class="terminal-header">Terminal</div>'
            f'<div class="terminal-body">{_esc(terminal_output)}</div>'
            "</div>"
        )

    status = _status_bar({
        "branch": "main",
        "language": language.capitalize(),
        "encoding": "UTF-8",
        "eol": "LF",
        "indent": "Spaces: 4",
        "position": f"Ln {cursor_line or 1} Col 1",
    })

    body = (
        '<div class="main-row">'
        f"{_activity_bar('files')}"
        '<div class="sidebar">'
        '<div class="sidebar-header">▼ Explorer</div>'
        f"{file_items}"
        "</div>"
        '<div class="editor-area">'
        f"{_tab_bar([filename], filename)}"
        '<div class="editor-content">'
        f'<div class="line-numbers">{lineno_html}</div>'
        f'<div class="code-area">{"".join(code_lines)}</div>'
        '<div class="minimap"></div>'
        "</div>"
        f"{terminal_html}"
        "</div>"
        "</div>"
        f"{status}"
        f"{_on_screen_label_html(on_screen_label)}"
    )
    return _wrap_page(body)


# ---------------------------------------------------------------------------
# Scene 2 – Terminal (maximised)
# ---------------------------------------------------------------------------
def terminal_scene(
    command: str,
    output: str,
    cwd: str | None = None,
    on_screen_label: str | None = None,
) -> str:
    """Return an HTML page showing VS Code with a maximised terminal.

    Parameters
    ----------
    command:
        Shell command (displayed with a ``$`` prefix in green).
    output:
        The command's stdout/stderr text.
    cwd:
        Optional working-directory string shown before the prompt.
    on_screen_label:
        Optional floating label.
    """
    prompt = _esc(cwd + " " if cwd else "")
    extra_css = f"""
    .full-terminal {{
        flex: 1; background: {_BG_TERMINAL}; display: flex;
        flex-direction: column; overflow: hidden;
    }}
    .full-terminal .term-header {{
        height: 35px; padding: 0 16px; display: flex; align-items: center;
        font-size: 11px; text-transform: uppercase; color: {_FG_DIM};
        border-bottom: 1px solid #333; letter-spacing: 0.5px;
        background: {_BG_TITLEBAR};
    }}
    .full-terminal .term-body {{
        flex: 1; padding: 12px 20px; font-family: {_FONT_CODE};
        font-size: 14px; line-height: 20px; white-space: pre;
        color: {_FG_DEFAULT}; overflow: hidden;
    }}
    .prompt-prefix {{ color: {_FG_COMMENT}; }}
    """

    status = _status_bar({
        "branch": "main",
        "language": "Terminal",
        "encoding": "UTF-8",
    })

    body = (
        '<div class="main-row">'
        f"{_activity_bar('files')}"
        '<div class="full-terminal">'
        '<div class="term-header">Terminal</div>'
        '<div class="term-body">'
        f'<span class="prompt-prefix">{prompt}$ </span>'
        f'<span style="color:{_FG_COMMENT}">{_esc(command)}</span>\n'
        f"{_esc(output)}"
        "</div>"
        "</div>"
        "</div>"
        f"{status}"
        f"{_on_screen_label_html(on_screen_label)}"
    )
    return _wrap_page(body, extra_css)


# ---------------------------------------------------------------------------
# Scene 3 – Extensions marketplace
# ---------------------------------------------------------------------------
def extensions_scene(
    search_query: str | None = None,
    extensions: list[dict[str, str]] | None = None,
    selected_extension: str | None = None,
    install_state: str | None = None,
    on_screen_label: str | None = None,
) -> str:
    """Return an HTML page showing VS Code's Extensions marketplace view.

    Parameters
    ----------
    search_query:
        Text shown in the search box.
    extensions:
        List of dicts with keys ``name``, ``publisher``, ``description``,
        ``icon_emoji``, and ``installs``.
    selected_extension:
        Name of the extension whose detail panel is shown.
    install_state:
        One of ``"install"``, ``"installing"``, ``"installed"``,
        ``"uninstall"`` — controls the action button displayed.
    on_screen_label:
        Optional floating label.
    """
    exts = extensions or []
    extra_css = f"""
    .ext-sidebar {{
        width: 350px; background: {_BG_SIDEBAR}; flex-shrink: 0;
        display: flex; flex-direction: column; overflow: hidden;
        border-right: 1px solid #333;
    }}
    .ext-search {{
        margin: 8px 10px; padding: 5px 10px; background: {_BG_INPUT};
        border: 1px solid #555; color: {_FG_DEFAULT}; font-size: 13px;
        font-family: {_FONT_UI}; border-radius: 2px;
    }}
    .ext-list {{ flex: 1; overflow: hidden; }}
    .ext-item {{
        padding: 10px 12px; display: flex; gap: 10px;
        cursor: default; border-bottom: 1px solid #333;
    }}
    .ext-item:hover, .ext-item.selected {{ background: rgba(255,255,255,0.06); }}
    .ext-icon {{ font-size: 28px; flex-shrink: 0; width: 36px; text-align: center; }}
    .ext-info {{ min-width: 0; }}
    .ext-name {{ font-weight: 600; font-size: 13px; }}
    .ext-pub {{ font-size: 11px; color: {_FG_DIM}; margin-top: 2px; }}
    .ext-desc {{ font-size: 12px; color: {_FG_DIM}; margin-top: 4px;
        white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}

    .ext-detail {{
        flex: 1; padding: 32px 40px; overflow: hidden;
        background: {_BG_EDITOR};
    }}
    .ext-detail h1 {{ font-size: 22px; margin-bottom: 4px; }}
    .ext-detail .pub {{ color: {_FG_DIM}; margin-bottom: 12px; font-size: 13px; }}
    .ext-detail .stars {{ color: #e8a825; font-size: 15px; margin-bottom: 16px; }}
    .ext-detail .btn {{
        display: inline-block; padding: 6px 20px; border-radius: 2px;
        font-size: 13px; font-weight: 600; cursor: default; margin-bottom: 20px;
    }}
    .btn-install {{ background: #0e639c; color: #fff; }}
    .btn-installing {{ background: #0e639c; color: #fff; opacity: 0.7; }}
    .btn-installed {{ background: #388a34; color: #fff; }}
    .btn-uninstall {{ background: #c72e2e; color: #fff; }}
    .ext-detail .desc {{ color: {_FG_DEFAULT}; line-height: 1.6; font-size: 14px; }}
    .ext-no-detail {{
        flex: 1; display: flex; align-items: center; justify-content: center;
        color: {_FG_DIM}; font-size: 14px; background: {_BG_EDITOR};
    }}
    """

    search_val = _esc(search_query) if search_query else ""
    search_box = (
        f'<input class="ext-search" value="{search_val}" '
        f'placeholder="Search Extensions in Marketplace" readonly>'
    )

    items_html_parts: list[str] = []
    for ext in exts:
        sel_cls = " selected" if ext.get("name") == selected_extension else ""
        items_html_parts.append(
            f'<div class="ext-item{sel_cls}">'
            f'<div class="ext-icon">{ext.get("icon_emoji", "🧩")}</div>'
            f'<div class="ext-info">'
            f'<div class="ext-name">{_esc(ext["name"])}</div>'
            f'<div class="ext-pub">by {_esc(ext["publisher"])}</div>'
            f'<div class="ext-desc">{_esc(ext["description"])}</div>'
            f"</div></div>"
        )

    # Detail panel
    detail_html = ""
    sel_ext = next((e for e in exts if e.get("name") == selected_extension), None)
    if sel_ext:
        btn_map = {
            "install": ('<span class="btn btn-install">Install</span>'),
            "installing": ('<span class="btn btn-installing">⟳ Installing…</span>'),
            "installed": ('<span class="btn btn-installed">✓ Installed</span>'),
            "uninstall": ('<span class="btn btn-uninstall">Uninstall</span>'),
        }
        btn = btn_map.get(install_state or "install", btn_map["install"])
        detail_html = (
            '<div class="ext-detail">'
            f'<h1>{_esc(sel_ext["name"])}</h1>'
            f'<div class="pub">by {_esc(sel_ext["publisher"])}</div>'
            f'<div class="stars">★★★★☆ ({_esc(sel_ext.get("installs", ""))} installs)</div>'
            f"{btn}"
            f'<div class="desc">{_esc(sel_ext["description"])}</div>'
            "</div>"
        )
    else:
        detail_html = '<div class="ext-no-detail">Select an extension to view details</div>'

    status = _status_bar({
        "branch": "main",
        "language": "Extensions",
        "encoding": "UTF-8",
    })

    body = (
        '<div class="main-row">'
        f"{_activity_bar('extensions')}"
        '<div class="ext-sidebar">'
        f"{search_box}"
        f'<div class="ext-list">{"".join(items_html_parts)}</div>'
        "</div>"
        f"{detail_html}"
        "</div>"
        f"{status}"
        f"{_on_screen_label_html(on_screen_label)}"
    )
    return _wrap_page(body, extra_css)


# ---------------------------------------------------------------------------
# Scene 4 – Copilot Chat
# ---------------------------------------------------------------------------
def chat_scene(
    messages: list[dict[str, str]],
    input_text: str | None = None,
    on_screen_label: str | None = None,
) -> str:
    """Return an HTML page showing VS Code with the Copilot Chat panel.

    Parameters
    ----------
    messages:
        List of dicts with ``"role"`` (``"user"`` or ``"assistant"``) and
        ``"content"`` keys.
    input_text:
        Text shown in the chat input field (simulates typing).
    on_screen_label:
        Optional floating label.
    """
    extra_css = f"""
    .chat-panel {{
        flex: 1; display: flex; flex-direction: column;
        background: {_BG_EDITOR}; overflow: hidden;
    }}
    .chat-header {{
        height: 35px; padding: 0 16px; display: flex; align-items: center;
        font-size: 13px; font-weight: 600; border-bottom: 1px solid #333;
        background: {_BG_TITLEBAR}; color: {_FG_DEFAULT};
    }}
    .chat-messages {{
        flex: 1; padding: 16px 20px; overflow: hidden;
        display: flex; flex-direction: column; gap: 16px;
    }}
    .chat-msg {{
        display: flex; gap: 10px; align-items: flex-start;
    }}
    .chat-avatar {{
        width: 28px; height: 28px; border-radius: 50%;
        display: flex; align-items: center; justify-content: center;
        font-size: 16px; flex-shrink: 0;
    }}
    .chat-avatar.user {{ background: #0e639c; }}
    .chat-avatar.assistant {{ background: #333; }}
    .chat-bubble {{
        background: {_BG_SIDEBAR}; border-radius: 6px;
        padding: 10px 14px; font-size: 14px; line-height: 1.55;
        max-width: 720px; white-space: pre-wrap; word-wrap: break-word;
    }}
    .chat-input-area {{
        padding: 10px 16px; border-top: 1px solid #333;
        display: flex; gap: 8px; align-items: center;
    }}
    .chat-input {{
        flex: 1; padding: 8px 12px; background: {_BG_INPUT};
        border: 1px solid #555; border-radius: 4px; color: {_FG_DEFAULT};
        font-size: 13px; font-family: {_FONT_UI};
    }}
    .chat-send {{
        padding: 8px 14px; background: #0e639c; color: #fff;
        border: none; border-radius: 4px; font-size: 13px;
        cursor: default;
    }}
    """

    msgs_html_parts: list[str] = []
    for msg in messages:
        role = msg.get("role", "user")
        icon = "👤" if role == "user" else "✨"
        avatar_cls = f"chat-avatar {role}"
        msgs_html_parts.append(
            f'<div class="chat-msg">'
            f'<div class="{avatar_cls}">{icon}</div>'
            f'<div class="chat-bubble">{_esc(msg.get("content", ""))}</div>'
            f"</div>"
        )

    input_val = _esc(input_text) if input_text else ""

    status = _status_bar({"branch": "main", "language": "Chat"})

    body = (
        '<div class="main-row">'
        f"{_activity_bar('chat')}"
        '<div class="chat-panel">'
        '<div class="chat-header">✨ Copilot Chat</div>'
        f'<div class="chat-messages">{"".join(msgs_html_parts)}</div>'
        '<div class="chat-input-area">'
        f'<input class="chat-input" value="{input_val}" '
        f'placeholder="Ask Copilot…" readonly>'
        '<button class="chat-send">Send</button>'
        "</div>"
        "</div>"
        "</div>"
        f"{status}"
        f"{_on_screen_label_html(on_screen_label)}"
    )
    return _wrap_page(body, extra_css)


# ---------------------------------------------------------------------------
# Scene 5 – Browser (Chrome-like)
# ---------------------------------------------------------------------------
def browser_scene(
    url: str,
    title: str,
    content_html: str,
    on_screen_label: str | None = None,
) -> str:
    """Return an HTML page showing a Chrome-like browser window.

    Parameters
    ----------
    url:
        URL displayed in the address bar.
    title:
        Page title shown in the browser tab.
    content_html:
        Raw HTML rendered in the browser viewport.
    on_screen_label:
        Optional floating label.
    """
    extra_css = f"""
    .browser {{
        width: 1920px; height: 1080px; display: flex;
        flex-direction: column; background: #202124;
        font-family: {_FONT_UI};
    }}
    .browser-tab-bar {{
        height: 38px; background: #202124; display: flex;
        align-items: flex-end; padding: 0 8px;
    }}
    .browser-tab {{
        padding: 6px 16px; background: #292a2d; color: {_FG_DEFAULT};
        font-size: 12px; border-radius: 8px 8px 0 0; max-width: 240px;
        white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    }}
    .browser-toolbar {{
        height: 40px; background: #292a2d; display: flex;
        align-items: center; padding: 0 12px; gap: 8px;
    }}
    .browser-nav-btn {{
        color: {_FG_DIM}; font-size: 16px; cursor: default;
        width: 28px; text-align: center;
    }}
    .browser-url {{
        flex: 1; padding: 5px 12px; background: #202124;
        border-radius: 16px; color: {_FG_DEFAULT}; font-size: 13px;
        border: none; font-family: {_FONT_UI};
    }}
    .browser-content {{
        flex: 1; background: #fff; overflow: hidden;
    }}
    """

    body = (
        '<div class="browser">'
        '<div class="browser-tab-bar">'
        f'<div class="browser-tab">{_esc(title)}</div>'
        "</div>"
        '<div class="browser-toolbar">'
        '<span class="browser-nav-btn">←</span>'
        '<span class="browser-nav-btn">→</span>'
        '<span class="browser-nav-btn">⟳</span>'
        f'<input class="browser-url" value="{_esc(url)}" readonly>'
        "</div>"
        f'<div class="browser-content">{content_html}</div>'
        "</div>"
        f"{_on_screen_label_html(on_screen_label)}"
    )
    return _wrap_page(body, extra_css)
