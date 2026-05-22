"""
Markdown → Telegram HTML converter.

Used by agent_chat replies. Claude (and most LLMs) emit standard markdown
(`**bold**`, `## heading`, `- bullets`, etc), but Telegram only parses
its own restricted HTML or MarkdownV2 — and we want HTML because fewer
characters need escaping.

Telegram HTML allowed tags (Bot API 7.0+):
    <b>/<strong>, <i>/<em>, <u>/<ins>, <s>/<strike>/<del>
    <tg-spoiler>, <a href="...">, <code>, <pre>, <blockquote>
Everything else is silently dropped or causes a parse error.

Special chars `&`, `<`, `>` MUST be escaped (with `&amp;`, `&lt;`, `&gt;`).
Inside <code>/<pre> the same escaping applies.

This module does NOT attempt to be a full markdown parser — it handles
the subset we actually observe in agent replies.
"""

from __future__ import annotations

import html
import re

# ---------------------------------------------------------------------------
# Code block extraction (process first, restore last)
# ---------------------------------------------------------------------------

_CODE_BLOCK_RE = re.compile(r"```(\w*)\n?(.*?)```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")


def _extract_code_blocks(text: str) -> tuple[str, list[str]]:
    """Replace ```code``` with placeholders, return (text, blocks).

    Placeholders are NUL-bounded so they survive other replacements.
    """
    blocks: list[str] = []

    def repl(m: re.Match) -> str:
        lang = m.group(1) or ""
        body = m.group(2)
        # Escape HTML inside code block
        escaped = html.escape(body, quote=False)
        if lang:
            html_block = f'<pre><code class="language-{lang}">{escaped}</code></pre>'
        else:
            html_block = f"<pre>{escaped}</pre>"
        blocks.append(html_block)
        return f"\x00CB{len(blocks) - 1}\x00"

    return _CODE_BLOCK_RE.sub(repl, text), blocks


def _extract_inline_code(text: str) -> tuple[str, list[str]]:
    blocks: list[str] = []

    def repl(m: re.Match) -> str:
        body = html.escape(m.group(1), quote=False)
        blocks.append(f"<code>{body}</code>")
        return f"\x00IC{len(blocks) - 1}\x00"

    return _INLINE_CODE_RE.sub(repl, text), blocks


def _restore(text: str, code_blocks: list[str], inline_code: list[str]) -> str:
    for i, block in enumerate(code_blocks):
        text = text.replace(f"\x00CB{i}\x00", block)
    for i, block in enumerate(inline_code):
        text = text.replace(f"\x00IC{i}\x00", block)
    return text


# ---------------------------------------------------------------------------
# Inline transformations
# ---------------------------------------------------------------------------

# Bold: **text** or __text__ (Claude almost always uses **)
# Use atomic group / minimal match to handle multi-asterisk safely.
_BOLD_RE = re.compile(r"\*\*([^\*\n][^\*]*?)\*\*", re.DOTALL)
# Italic: single * around text (but not part of **). We process AFTER bold.
# Match *text* where neither boundary is another asterisk.
_ITALIC_AST_RE = re.compile(r"(?<![\*\w])\*(?!\s)([^\*\n]+?)(?<!\s)\*(?!\*)")
# Italic with underscore: _text_ (avoid matching inside words like a_b_c)
_ITALIC_UND_RE = re.compile(r"(?<![\w])_(?!\s)([^_\n]+?)(?<!\s)_(?!\w)")
# Strikethrough: ~~text~~
_STRIKE_RE = re.compile(r"~~([^~\n]+?)~~")
# Link: [text](url) — only http/https for safety
_LINK_RE = re.compile(r"\[([^\]\n]+)\]\((https?://[^\)\s]+)\)")


def _apply_inline(text: str) -> str:
    text = _BOLD_RE.sub(lambda m: f"<b>{m.group(1)}</b>", text)
    text = _STRIKE_RE.sub(lambda m: f"<s>{m.group(1)}</s>", text)
    text = _LINK_RE.sub(lambda m: f'<a href="{m.group(2)}">{m.group(1)}</a>', text)
    # Italic last (single-char delimiters are noisier)
    text = _ITALIC_AST_RE.sub(lambda m: f"<i>{m.group(1)}</i>", text)
    text = _ITALIC_UND_RE.sub(lambda m: f"<i>{m.group(1)}</i>", text)
    return text


# ---------------------------------------------------------------------------
# Block transformations
# ---------------------------------------------------------------------------

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
# Bullet list item: -, *, • at line start (after optional whitespace)
_BULLET_RE = re.compile(r"^(\s*)[-*]\s+", re.MULTILINE)
# Horizontal rule: --- or *** or ___ on own line
_HR_RE = re.compile(r"^\s*(?:---+|\*\*\*+|___+)\s*$", re.MULTILINE)
# Table row: starts and ends with |
_TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$", re.MULTILINE)
# Separator row in markdown table: |---|---|
_TABLE_SEP_RE = re.compile(r"^\s*\|[\s\-:|]+\|\s*$", re.MULTILINE)


def _flatten_tables(text: str) -> str:
    """Markdown tables → bullet-style lines.

    Telegram HTML doesn't support tables. Convert each data row to:
        • col1: col2 | col3: col4
    using the header row's column names. Drop the separator row.
    """
    lines = text.split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if _TABLE_ROW_RE.match(line) and i + 1 < len(lines) and _TABLE_SEP_RE.match(lines[i + 1]):
            # Found a table: header + sep + N data rows
            header = [c.strip() for c in line.strip().strip("|").split("|")]
            i += 2
            while i < len(lines) and _TABLE_ROW_RE.match(lines[i]):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                pairs = []
                for col, val in zip(header, cells):
                    if not val:
                        continue
                    if col:
                        pairs.append(f"{col}: {val}")
                    else:
                        pairs.append(val)
                out.append("• " + " · ".join(pairs))
                i += 1
        else:
            out.append(line)
            i += 1
    return "\n".join(out)


def _apply_blocks(text: str) -> str:
    # Tables first — they're row-oriented and easier before other transforms.
    text = _flatten_tables(text)
    # Horizontal rules: drop entirely (Telegram doesn't render <hr>).
    text = _HR_RE.sub("", text)
    # Headings → <b>...</b> (Telegram has no h1/h2). Keep on own line.
    text = _HEADING_RE.sub(lambda m: f"<b>{m.group(2)}</b>", text)
    # Bullet markers `-` / `*` at line start → `•` (keep indentation)
    text = _BULLET_RE.sub(lambda m: f"{m.group(1)}• ", text)
    return text


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


# Telegram message hard-limit = 4096 байт. После markdown→HTML текст может
# подрасти (escape `<>&`, обёртки тегов в заголовках). Берём запас:
# 3500 байт markdown → ≤ ~4000 байт HTML в реалистичных случаях.
TELEGRAM_SAFE_CHUNK = 3500


def split_markdown_for_telegram(text: str, max_chunk: int = TELEGRAM_SAFE_CHUNK) -> list[str]:
    """Разбить markdown-текст на куски, безопасные для одного Telegram-сообщения.

    Приоритет точек разреза:
      1. Двойной перевод строки (\\n\\n — абзац).
      2. Одинарный перевод строки.
      3. Точка с пробелом (граница предложения).
      4. Жёсткий обрыв по `max_chunk`.

    Гарантия: НЕ режем внутри ```код```. Если внутри окна нечётное число
    ограничителей — расширяем окно до закрывающей тройной кавычки.
    """
    if not text or len(text) <= max_chunk:
        return [text] if text else []

    chunks: list[str] = []
    remaining = text
    min_split = max_chunk // 2  # не режем слишком близко к началу окна

    while len(remaining) > max_chunk:
        window_end = max_chunk
        # Внутри открытого ```код``` — продлеваем окно до его закрытия.
        if remaining[:window_end].count("```") % 2 == 1:
            close = remaining.find("```", window_end)
            if close >= 0:
                window_end = close + 3
        window = remaining[:window_end]

        split_at = window.rfind("\n\n")
        if split_at < min_split:
            split_at = window.rfind("\n")
        if split_at < min_split:
            sentence = window.rfind(". ")
            split_at = sentence + 1 if sentence >= min_split else -1
        if split_at < min_split:
            split_at = window_end  # hard cut

        chunks.append(remaining[:split_at].rstrip())
        remaining = remaining[split_at:].lstrip()

    if remaining:
        chunks.append(remaining)
    return chunks


def md_to_html(text: str) -> str:
    """Convert a subset of Markdown → Telegram HTML.

    Pipeline:
        1. extract fenced code blocks (escape HTML inside, replace with placeholder)
        2. extract inline `code` (same)
        3. HTML-escape the remaining `&`, `<`, `>`
        4. apply block-level transforms (## headings, - bullets)
        5. apply inline transforms (**bold**, *italic*, ~~strike~~, [link](url))
        6. restore code placeholders

    Step order matters: HTML escape MUST happen before inline transforms
    insert tags; code blocks MUST be extracted before HTML escape so their
    bodies are escaped separately and embedded into <pre>/<code> tags.
    """
    if not text:
        return ""
    text, code_blocks = _extract_code_blocks(text)
    text, inline_code = _extract_inline_code(text)
    text = html.escape(text, quote=False)
    text = _apply_blocks(text)
    text = _apply_inline(text)
    return _restore(text, code_blocks, inline_code)
