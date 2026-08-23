#!/usr/bin/env python3
"""Render the verbatim trace as a page a human can actually read.

The brief is explicit that the trace must be the REAL conversation, verbatim,
and that a hand-made one tells them nothing. So this script changes PRESENTATION
and nothing else: it does not drop a message, reorder anything, shorten a line
or soften a word. Feed it the markdown that `export_trace.py` produced and it
emits one HTML page.

What the page adds over the raw file, and why each is presentation rather than
editing:

  * The exporter marks tool RESULTS with the same `User` role the human has -
    that is how the transcript stores them. 112 of the 123 "User" blocks are
    machine output. The page labels them apart and folds them shut, so the
    eleven things the human actually said are findable. Both are still there.
  * An index down the side lists the human's messages in order, so the shape of
    the session - where it was redirected, where it went wrong - is visible
    without scrolling through 5,000 lines.
  * Long tool output is behind a disclosure triangle. Nothing is truncated by
    this script; the only truncation is the one `export_trace.py` performed and
    annotated in the file itself.

    python render_trace.py TRACE-task1.redacted.md -o docs/trace.html
    python render_trace.py --self-test
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
from pathlib import Path

HEADER = re.compile(r"^### (\d+) [·•] (.+?)\s*$")
STAMP = re.compile(r"^`(\d{4}-\d{2}-\d{2}T[0-9:.]+Z?)`\s*$")
FENCE = re.compile(r"^```(\w*)\s*$")
TOOL_CALL = re.compile(r"^\*\*-> tool: `(.+?)`\*\*", re.M)
TOOL_RESULT = re.compile(r"^\*\*<- result\*\*", re.M)
# Machine text wearing the human's role.
HARNESS_IN_USER_TURN = re.compile(
    r"^\s*(?:<task-notification>|Stop hook feedback:|Caveat:|\[Request interrupted)", re.M)


def split_blocks(text: str):
    """One dict per message, in file order. Nothing is dropped or merged."""
    lines = text.splitlines()
    preamble, blocks, current = [], [], None
    for line in lines:
        match = HEADER.match(line)
        if match:
            if current:
                blocks.append(current)
            current = {"n": int(match.group(1)), "role": match.group(2), "ts": None, "lines": []}
            continue
        if current is None:
            preamble.append(line)
            continue
        if current["ts"] is None and not current["lines"]:
            stamp = STAMP.match(line.strip())
            if stamp:
                current["ts"] = stamp.group(1)
                continue
        current["lines"].append(line)
    if current:
        blocks.append(current)
    return "\n".join(preamble).strip(), blocks


def classify(block) -> str:
    """human | tool_result | assistant | tool_call | system.

    The transcript files tool results under the user's own role, which is what
    made an earlier count of "91 user messages" wrong by 88. Separating them is
    the whole reason this page is easier to read than the raw markdown.
    """
    body = "\n".join(block["lines"])
    role = block["role"]
    if role.startswith("System"):
        return "system"
    if role.startswith("User"):
        if TOOL_RESULT.search(body):
            return "tool_result"
        # A background agent finishing, or a hook answering back, arrives on the
        # human's own channel. The exporter labels these correctly now, but the
        # trace that shipped before that fix still calls one of them a message
        # the person typed - which is why its header says eleven and the truth
        # is ten. Content decides, not the label in the file.
        return "system" if HARNESS_IN_USER_TURN.search(body) else "human"
    return "tool_call" if TOOL_CALL.search(body) else "assistant"


REPO = Path(__file__).resolve().parent
BLOB = "https://github.com/AnastasiyaW/explee-spend-observability/blob/main/"


def _link(match) -> str:
    """Resolve a link the way a reader needs, without touching its text.

    The trace was written from the repository root; the page is served out of
    docs/, so every relative target in it 404s. A target that exists in the
    repository becomes a blob URL. A target that does not - a handoff, a rule,
    anything living outside this repo - keeps its text and loses the anchor,
    because a dead link is worse than no link.
    """
    text, target = match.group(1), match.group(2)
    if target.startswith(("http://", "https://", "#", "mailto:")):
        return '<a href="{}">{}</a>'.format(target, text)
    local = target.split("#", 1)[0]
    if local and (REPO / local).exists():
        return '<a href="{}{}">{}</a>'.format(BLOB, local, text)
    # The target is real but lives outside this repository - a handoff, a rule.
    # Linking it would 404; dropping it would lose what the writer pointed at.
    # So it stays, as text.
    return '{} <span class="deadpath">{}</span>'.format(text, target)


def md_inline(text: str) -> str:
    """Escape first, then re-introduce only the marks the exporter itself writes."""
    out = html.escape(text, quote=False)
    out = re.sub(r"`([^`]+)`", r"<code>\1</code>", out)
    out = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", out)
    out = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", _link, out)
    return out


def md_body(lines) -> str:
    """A deliberately small markdown subset: fences, lists, quotes, paragraphs."""
    parts, buffer, fence_lang, fenced = [], [], None, []

    def flush_paragraph():
        if buffer:
            parts.append("<p>" + "<br>".join(md_inline(x) for x in buffer) + "</p>")
            buffer.clear()

    in_fence = False
    for line in lines:
        fence = FENCE.match(line)
        if fence and not in_fence:
            flush_paragraph()
            in_fence, fence_lang, fenced = True, fence.group(1), []
            continue
        if in_fence:
            if line.strip() == "```":
                lang = ' class="lang-{}"'.format(fence_lang) if fence_lang else ""
                parts.append("<pre{}><code>{}</code></pre>".format(
                    lang, html.escape("\n".join(fenced), quote=False)))
                in_fence = False
                continue
            fenced.append(line)
            continue
        if not line.strip():
            flush_paragraph()
            continue
        if re.match(r"^\s*[-*] ", line):
            flush_paragraph()
            parts.append("<ul><li>" + md_inline(re.sub(r"^\s*[-*] ", "", line)) + "</li></ul>")
            continue
        if line.startswith("> "):
            flush_paragraph()
            parts.append("<blockquote>" + md_inline(line[2:]) + "</blockquote>")
            continue
        if line.startswith("#### "):
            flush_paragraph()
            parts.append("<h4>" + md_inline(line[5:]) + "</h4>")
            continue
        buffer.append(line)
    if in_fence:                      # an unterminated fence is still content
        parts.append("<pre><code>{}</code></pre>".format(
            html.escape("\n".join(fenced), quote=False)))
    flush_paragraph()
    # Consecutive one-item lists read as one list.
    return re.sub(r"</ul>\s*<ul>", "", "\n".join(parts))


def first_line(block) -> str:
    for line in block["lines"]:
        if line.strip():
            return re.sub(r"\s+", " ", line.strip())
    return ""


SESSION_TITLES = {
    "TRACE-task1.redacted.md": "Session 1 - Claude Code, building the collector",
    "TRACE-task1-codex.redacted.md": "Session 2 - Codex, carrying it on",
    "TRACE-task1-review.redacted.md": "Session 3 - Claude Code, review and hardening",
}

LABEL = {
    "human": ("Human", "the person"),
    "assistant": ("Agent", "reasoning and answers"),
    "tool_call": ("Tool call", "what the agent ran"),
    "tool_result": ("Tool result", "what came back"),
    "system": ("Harness", "injected by the tooling, not typed by anyone"),
}

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Agent trace · Task 1</title>
<link rel="stylesheet" href="site.css">
<style>
  /* Tokens, type scale, header, code, footer and the language switch come from
     site.css - the same file the other three pages load. What is left here is
     only the trace's own furniture: the two-column shell, the rail of human
     messages, and the message blocks themselves. */
  .shell{{display:grid;grid-template-columns:264px minmax(0,1fr);gap:24px;
    max-width:1220px;margin:0 auto;padding:30px 18px 80px}}
  @media (max-width:900px){{ .shell{{grid-template-columns:1fr}} .rail{{position:static;max-height:none}} }}
  .rail{{position:sticky;top:20px;align-self:start;max-height:88vh;overflow:auto;padding:11px 6px}}
  .rail h3{{font-size:11px;text-transform:uppercase;letter-spacing:.1em;color:var(--muted);
    margin:4px 10px 8px;font-weight:600}}
  .rail a{{display:block;color:inherit;text-decoration:none;font-size:12.5px;line-height:1.45;
    padding:7px 10px;border-radius:var(--r-sm);border-left:2px solid transparent}}
  .rail a:hover{{background:var(--hover);border-left-color:var(--human)}}
  .rail a b{{display:block;font-size:10.5px;color:var(--muted);font-weight:600;
    letter-spacing:.05em;text-transform:uppercase}}
  .lede a{{color:var(--accent)}}

  .facts{{display:flex;gap:16px;flex-wrap:wrap;font-size:12.5px;color:var(--muted);
    padding:10px 14px;margin:0 0 18px;font-variant-numeric:tabular-nums}}
  .facts b{{color:var(--ink);font-weight:650}}

  /* Who said it is carried by one 3px edge, the same device the landing uses
     to group its cards: the person and the agent are coloured, the machinery
     between them is not. */
  .msg{{border:1px solid var(--line);border-radius:var(--r);background:var(--panel);
    padding:13px 16px;margin:0 0 10px;scroll-margin-top:16px;
    box-shadow:inset 3px 0 0 var(--line)}}
  .msg.human{{box-shadow:inset 3px 0 0 var(--human)}}
  .msg.assistant{{box-shadow:inset 3px 0 0 var(--accent)}}
  .who{{display:flex;gap:10px;align-items:baseline;font-size:11px;text-transform:uppercase;
    letter-spacing:.07em;color:var(--muted);margin:0 0 7px}}
  .who .n{{font-weight:700;color:var(--ink);font-variant-numeric:tabular-nums}}
  .who .role{{font-weight:650}}
  .msg.human .who .role{{color:var(--human)}}
  .msg.assistant .who .role{{color:var(--accent)}}
  .who time{{margin-left:auto;font:11px var(--f-mono);text-transform:none}}
  .msg p{{margin:0 0 9px}} .msg p:last-child{{margin-bottom:0}}
  blockquote{{margin:0 0 9px;padding-left:11px;border-left:2px solid var(--line);color:var(--muted)}}
  ul{{margin:0 0 9px;padding-left:20px}}
  details summary{{cursor:pointer;color:var(--muted);font-size:12.5px;list-style:none}}
  details summary::-webkit-details-marker{{display:none}}
  details summary::before{{content:"\\25b8 ";color:var(--muted)}}
  details[open] summary::before{{content:"\\25be "}}
  details[open] summary{{margin-bottom:8px}}
  .peek{{font:12px var(--f-mono);color:var(--muted)}}

  /* Machinery, listed rather than laid out. Most of a trace is ordinary shell;
     as full blocks it buries the few things the person said. */
  .msg.toolrun{{padding:10px 16px}}
  ol.tools{{margin:0;padding:0;list-style:none}}
  ol.tools li{{padding:2px 0;border-bottom:1px solid var(--grid)}}
  ol.tools li:last-child{{border-bottom:0}}
  ol.tools summary{{display:flex;gap:9px;align-items:baseline}}
  ol.tools summary::before{{content:none}}
  ol.tools .tick{{font:600 9.5px/1.8 var(--f-sans);letter-spacing:.09em;text-transform:uppercase;
    color:var(--muted);border:1px solid var(--line);border-radius:4px;padding:0 5px;flex:none}}
  ol.tools li.tool_call .tick{{color:var(--accent);border-color:var(--accent)}}
  ol.tools .peek{{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1}}
  ol.tools time{{margin-left:auto;font:10.5px var(--f-mono);color:var(--muted);flex:none}}
  .deadpath{{font:11.5px var(--f-mono);color:var(--muted)}}

  .partline{{display:flex;gap:12px;align-items:baseline;flex-wrap:wrap;
    font-size:13px;font-weight:650;letter-spacing:-.01em;color:var(--ink);
    margin:26px 0 10px;padding-bottom:7px;border-bottom:1px solid var(--line)}}
  .partline:first-of-type{{margin-top:0}}
  .partline span{{font-weight:400;font-size:12px;color:var(--muted)}}
  .rail h3.part{{margin-top:14px;color:var(--ink)}}

  /* As typed by default; the corrected reading is a switch, never a rewrite. */
  .fixed{{display:none}}
  body.corrected .asis{{display:none}}
  body.corrected .fixed{{display:block}}
  .reading{{display:flex;gap:9px;align-items:center;font-size:12px;color:var(--muted);
    margin:0 0 18px}}
  .reading button{{font:600 11px/1 var(--f-sans);letter-spacing:.05em;text-transform:uppercase;
    border:1px solid var(--line);background:var(--panel);color:var(--muted);cursor:pointer;
    border-radius:20px;padding:5px 10px}}
  .reading button[aria-pressed="true"]{{background:var(--accent);border-color:var(--accent);
    color:var(--on-accent)}}
</style>
<script src="i18n.js"></script>
</head>
<body>
<div class="shell">
  <nav class="panel rail">
    <h3 data-i18n="trace.rail">What the human said</h3>
{rail}
  </nav>
  <main>
    <header class="pagehead">
      <nav class="backrow"><a class="back" href="./" data-i18n="spend.back">&larr; all three tasks</a></nav>
      <h1 data-i18n="trace.h1">Agent trace &middot; Task 1</h1>
      <p class="lede" data-i18n="trace.lede">{lede}</p>
    </header>
    <div class="panel facts">
      <span><b>{total}</b> <span data-i18n="trace.f.total">messages</span></span>
      <span><b>{humans}</b> <span data-i18n="trace.f.human">from the human</span></span>
      <span><b>{assistants}</b> <span data-i18n="trace.f.agent">from the agent</span></span>
      <span><b>{calls}</b> <span data-i18n="trace.f.calls">tool calls</span></span>
      <span><b>{results}</b> <span data-i18n="trace.f.results">tool results</span></span>
    </div>
    <div class="reading">
      <span data-i18n="trace.reading">Reading</span>
      <button type="button" data-reading="asis" aria-pressed="true"
              data-i18n="trace.reading.asis">as typed</button>
      <button type="button" data-reading="fixed" aria-pressed="false"
              data-i18n="trace.reading.fixed">spelling corrected</button>
      <span class="peek" data-i18n="trace.reading.note">the record is the verbatim file; this
        only fixes typos in the human's own messages</span>
    </div>
{body}
    <footer data-i18n="trace.foot">{foot}</footer>
  </main>
</div>
<script>
// The default is the record. Switching is a reading aid and says so.
document.querySelectorAll("[data-reading]").forEach(function (button) {{
  button.addEventListener("click", function () {{
    var corrected = button.getAttribute("data-reading") === "fixed";
    document.body.classList.toggle("corrected", corrected);
    document.querySelectorAll("[data-reading]").forEach(function (other) {{
      other.setAttribute("aria-pressed",
        String(other.getAttribute("data-reading") === (corrected ? "fixed" : "asis")));
    }});
  }});
}});
</script>
</body>
</html>
"""


def apply_corrections(text: str, pairs) -> str:
    """Spelling only, and only where the pair matches exactly once.

    A pair that matches nothing is a correction that silently did not happen; a
    pair that matches twice is a correction landing somewhere nobody checked.
    Both raise rather than pass, because the whole value of offering a corrected
    reading is that a reader can trust which characters moved.
    """
    for find, replace in pairs:
        hits = text.count(find)
        if hits != 1:
            raise ValueError("correction matches {} times, expected exactly 1: {!r}".format(
                hits, find[:70]))
        text = text.replace(find, replace, 1)
    return text


def human_block(block, corrections) -> str:
    """The human's words as typed, plus - if offered - a corrected reading.

    The brief asks for the real conversation and says a hand-made trace tells
    them nothing, so the verbatim text is what the page shows by default and
    what the committed file contains. The corrected reading is a switch, built
    from an explicit list of find/replace pairs that lives in the repository,
    so which characters changed is auditable instead of buried in a rewritten
    file.
    """
    verbatim = md_body(block["lines"])
    pairs = corrections.get(str(block["n"])) if corrections else None
    if not pairs:
        return verbatim
    raw = "\n".join(block["lines"])
    fixed = md_body(apply_corrections(raw, pairs).splitlines())
    return ('<div class="asis">{}</div><div class="fixed">{}</div>'.format(verbatim, fixed))


def render_part(markdown_text: str, source_name: str, prefix: str, corrections=None):
    """One session: its rail entries, its message blocks, its counts."""
    preamble, blocks = split_blocks(markdown_text)
    kinds = [classify(b) for b in blocks]
    rail, body = [], []
    index = 0
    while index < len(blocks):
        block, kind = blocks[index], kinds[index]
        anchor = "{}m{}".format(prefix, block["n"])

        # A run of machinery collapses into one numbered list. Most of this
        # trace is ordinary shell, and rendered as full blocks it buries the
        # handful of things the human said under thousands of lines of output.
        # Every character is still here, one disclosure triangle away.
        if kind in ("tool_call", "tool_result"):
            run_start, rows = index, []
            while index < len(blocks) and kinds[index] in ("tool_call", "tool_result"):
                item, item_kind = blocks[index], kinds[index]
                rows.append(
                    '<li class="{}" id="{}m{}"><details><summary>'
                    '<span class="tick">{}</span><span class="peek">{}</span>{}</summary>{}'
                    '</details></li>'.format(
                        item_kind, prefix, item["n"],
                        "run" if item_kind == "tool_call" else "out",
                        html.escape(first_line(item)[:120], quote=False),
                        # The stamp travels with the row. Folding a block must not
                        # drop what the block carried, and --verify says so.
                        '<time>{}</time>'.format(html.escape(item["ts"])) if item["ts"] else "",
                        md_body(item["lines"])))
                index += 1
            body.append(
                '<section class="msg toolrun"><div class="who"><span class="n">{}&ndash;{}</span>'
                '<span class="role">Tool activity</span><span>{} steps, folded</span></div>'
                '<ol class="tools">{}</ol></section>'.format(
                    blocks[run_start]["n"], blocks[index - 1]["n"], len(rows), "".join(rows)))
            continue

        label, hint = LABEL[kind]
        stamp = '<time>{}</time>'.format(html.escape(block["ts"])) if block["ts"] else ""
        head = ('<div class="who"><span class="n">{}</span>'
                '<span class="role">{}</span><span>{}</span>{}</div>').format(
                    block["n"], label, hint, stamp)
        content = md_body(block["lines"])
        if kind == "system":
            peek = html.escape(first_line(block)[:110], quote=False)
            content = ("<details><summary><span class=\"peek\">{}</span></summary>{}</details>"
                       .format(peek or label, content))
        elif kind == "human":
            content = human_block(block, corrections)
        body.append('<section class="msg {}" id="{}">{}{}</section>'.format(kind, anchor, head, content))
        if kind == "human":
            rail.append('    <a href="#{}"><b>{}</b>{}</a>'.format(
                anchor, block["n"], html.escape(first_line(block)[:96], quote=False)))
        index += 1

    return {
        "rail": rail,
        "body": body,
        "preamble": preamble,
        "source": source_name,
        "total": len(blocks),
        "humans": kinds.count("human"),
        "assistants": kinds.count("assistant"),
        "calls": kinds.count("tool_call"),
        "results": kinds.count("tool_result"),
    }


def render(sources, corrections=None) -> str:
    """One page, one session per part, in the order they were given.

    The work ran across two harnesses. Splitting the trace across two files a
    reader has to find separately would hide half of it; renumbering the two
    into one sequence would misrepresent both. So each part keeps its own
    numbering and says which session it is.
    """
    corrections = corrections or {}
    parts = []
    for position, (text, name) in enumerate(sources, start=1):
        parts.append(render_part(text, name, "s{}".format(position),
                                 corrections.get(name)))

    rail, body = [], []
    for position, part in enumerate(parts, start=1):
        if len(parts) > 1:
            title = SESSION_TITLES.get(part["source"], part["source"])
            rail.append('    <h3 class="part">{}</h3>'.format(html.escape(title)))
            body.append(
                '<h2 class="partline" id="part{}">{}<span>{} messages &middot; {} from the human'
                '</span></h2>'.format(position, html.escape(title), part["total"], part["humans"]))
        rail.extend(part["rail"])
        body.extend(part["body"])

    total = sum(p["total"] for p in parts)
    humans = sum(p["humans"] for p in parts)
    links = " &middot; ".join(
        '<a href="{}{}">{}</a>'.format(BLOB, html.escape(p["source"]), html.escape(p["source"]))
        for p in parts)
    lede = (
        'The real sessions, verbatim, in order. This page only changes how they are laid out: '
        'nothing is removed, reordered or reworded. Tool results arrive under the same "user" '
        'role as the person, so they are labelled apart and folded into lists - that, and '
        'nothing else, is why this reads more easily than the files of record: {links}.'
    ).format(links=links)
    foot = (
        'Generated by <a href="{blob}render_trace.py">render_trace.py</a>, which is in the '
        'repository and can be re-run against the same input; its <code>--verify</code> checks '
        'that every non-empty source line survived the rendering. The export itself, and the bug '
        'that nearly lost most of the human&rsquo;s messages, are documented in the header of '
        '<code>export_trace.py</code>. Placeholders like <code>&lt;PRIVATE-4&gt;</code> are '
        'per file: the same placeholder in two parts is not necessarily the same original.'
    ).format(blob=BLOB)
    for part in parts:
        if part["preamble"]:
            foot += "<br><br>" + md_body(part["preamble"].splitlines())
    return PAGE.format(
        rail="\n".join(rail) or '    <a href="#">no human messages found</a>',
        body="\n".join(body),
        lede=lede, foot=foot,
        total=total, humans=humans,
        assistants=sum(p["assistants"] for p in parts),
        calls=sum(p["calls"] for p in parts),
        results=sum(p["results"] for p in parts),
    )


def self_test() -> int:
    failures = []
    sample = (
        "# TRACE\n\nPreamble line.\n\n---\n\n"
        "### 1 · User  \n`2026-08-23T08:43:18.002Z`\n\nHello <b>&</b> welcome\n\n"
        "### 2 · Assistant  \n\n**-> tool: `Bash`**\n\n```bash\nls -la\n```\n\n"
        "### 3 · User  \n\n**<- result**\n\n```\ntotal 0\n```\n\n"
        "### 4 · Assistant  \n\nDone, see `file.py`.\n"
    )
    preamble, blocks = split_blocks(sample)
    if len(blocks) != 4:
        failures.append("split found {} blocks, expected 4".format(len(blocks)))
    kinds = [classify(b) for b in blocks]
    if kinds != ["human", "tool_call", "tool_result", "assistant"]:
        failures.append("classification is {}".format(kinds))
    if "Preamble line." not in preamble:
        failures.append("the preamble was dropped")
    page = render([(sample, "T.md")])
    # The whole promise of this script is that it drops nothing.
    for needle in ("Hello", "welcome", "ls -la", "total 0", "Done, see"):
        if needle not in page:
            failures.append("content lost in rendering: " + needle)
    if "<b>&</b>" in page:
        failures.append("raw markup from the transcript reached the page unescaped")
    if "&lt;b&gt;" not in page:
        failures.append("markup in a message was not escaped into visible text")
    # Three sections now: the human, the folded tool run, the closing answer.
    if page.count('class="msg') != 3:
        failures.append("expected three sections, got {}".format(page.count('class="msg')))
    if 'class="msg toolrun"' not in page:
        failures.append("the tool call and its result were not folded into one list")
    human_section = page.split('id="s1m1"')[1].split("</section>")[0]
    if "<details>" in human_section:
        failures.append("a human message was folded shut")

    # A harness notification wearing the human's role is not the human.
    harness = ("### 1 · User  \n\n<task-notification>\n<task-id>x</task-id>\n</task-notification>\n"
               "\n### 2 · User  \n\nreal words\n")
    kinds = [classify(b) for b in split_blocks(harness)[1]]
    if kinds != ["system", "human"]:
        failures.append("a task notification counted as a human message: {}".format(kinds))

    # Corrections: exactly-once or it is an error, and both readings ship.
    corrected = render([(sample, "T.md")], {"T.md": {"1": [["welcome", "welcome!"]]}})
    if 'class="asis"' not in corrected or 'class="fixed"' not in corrected:
        failures.append("the corrected reading was not rendered beside the verbatim one")
    if "welcome!" not in corrected or "Hello" not in corrected:
        failures.append("a correction did not reach the corrected reading")
    for pairs, why in (([["nowhere", "x"]], "a pattern that matches nothing"),
                       ([["l", "L"]], "a pattern that matches many times")):
        try:
            render([(sample, "T.md")], {"T.md": {"1": pairs}})
            failures.append("silently accepted " + why)
        except ValueError:
            pass

    # Two sessions render as two parts, each keeping its own numbering.
    two = render([(sample, "TRACE-task1.redacted.md"), (sample, "TRACE-task1-codex.redacted.md")])
    if two.count('class="partline"') != 2:
        failures.append("two sources did not render as two parts")
    if 'id="s2m1"' not in two:
        failures.append("the second part's anchors collide with the first")

    # A link to a file that is not in the repository must not ship as a link.
    linked = render([("### 1 · User  \n\nsee [a](PROBLEMS.md) and [b](.claude/handoffs/x.md)\n",
                      "T.md")])
    if 'href="{}PROBLEMS.md"'.format(BLOB) not in linked:
        failures.append("a repo-relative link was not resolved to a blob URL")
    if "handoffs/x.md" in linked and 'href=".claude/handoffs/x.md"' in linked:
        failures.append("a link to a file outside the repository shipped as a 404")
    if failures:
        print("SELF-TEST: FAIL")
        for item in failures:
            print("  - " + item)
        return 1
    print("SELF-TEST: PASS")
    return 0


def _marks(text: str) -> str:
    """Drop the inline marks md_inline consumes, and collapse whitespace."""
    return re.sub(r"\s+", " ", text.replace("`", "").replace("*", "")).strip()


def _plain_page(page: str) -> str:
    """Page text as a reader sees it.

    Tags are stripped BEFORE unescaping, and the order is the whole point: a
    transcript full of `<system-reminder>` and `GET /<provider>/balance` writes
    those angle brackets as entities, so unescaping first would turn message
    content into something the next regex deletes. Getting this backwards is how
    a checker reports 279 lost lines that were never lost.
    """
    return _marks(html.unescape(re.sub(r"<[^>]+>", "", page)))


def verify(markdown_text: str, page: str):
    """Every line of the source must be findable in the page. That is the promise.

    The page claims nothing was removed. A claim like that is worth exactly as
    much as the check behind it, so this compares the two directly rather than
    sampling. Section headers are excluded: they become the role chrome above
    each message and are structure, not anything anyone said.
    """
    haystack = _plain_page(page)
    missing = []
    for raw in markdown_text.splitlines():
        if HEADER.match(raw):
            continue
        # A bullet becomes a list marker and a quote becomes a rule down the
        # side; both are markdown syntax rather than something someone wrote.
        line = re.sub(r"^\s*(?:[-*] |> |#{1,6} )", "", raw)
        # A link keeps its text on screen and moves its target into the href,
        # so the target is checked against the raw page instead of the text.
        for target in re.findall(r"\[[^\]]+\]\(([^)\s]+)\)", line):
            if html.escape(target, quote=True) not in page and target not in page:
                missing.append(raw.strip())
        # Outside a fence a link renders as its text; inside one it stays
        # literal. Either form counts as survived - the line is only lost if
        # neither appears.
        # Three renderings a link can take: literal inside a fence, text only
        # when it resolved to an anchor, and text plus target when it pointed
        # outside the repository and kept the path visible instead of 404ing.
        forms = {
            _marks(line),
            _marks(re.sub(r"\[([^\]]+)\]\([^)\s]+\)", r"\1", line)),
            _marks(re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", r"\1 \2", line)),
        }
        forms = {f for f in forms if len(f) >= 3}
        if not forms:
            continue
        if not any(f in haystack for f in forms):
            missing.append(raw.strip())
    return sorted(set(missing), key=missing.index)


def main(argv) -> int:
    ap = argparse.ArgumentParser(description="Render a verbatim trace as one HTML page")
    ap.add_argument("sources", nargs="*",
                    help="TRACE markdown files, in the order the sessions happened")
    ap.add_argument("-o", "--out", default="docs/trace.html")
    ap.add_argument("--corrections", default="trace-corrections.json",
                    help="spelling corrections offered as an alternative reading")
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--verify", action="store_true",
                    help="after rendering, prove every source line survived")
    args = ap.parse_args(argv)
    if args.self_test:
        return self_test()
    if not args.sources:
        ap.error("at least one source file is required")

    corrections = {}
    corrections_path = Path(args.corrections)
    if corrections_path.exists():
        loaded = json.loads(corrections_path.read_text(encoding="utf-8"))
        corrections = {k: v for k, v in loaded.items() if isinstance(v, dict)}

    loaded_sources = []
    for name in args.sources:
        path = Path(name)
        loaded_sources.append((path.read_text(encoding="utf-8"), path.name))

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    page = render(loaded_sources, corrections)
    out.write_text(page, encoding="utf-8")
    for text, name in loaded_sources:
        kinds = [classify(b) for b in split_blocks(text)[1]]
        print("{:<34} {:>4} messages, {:>3} from the human".format(
            name, len(kinds), kinds.count("human")))
    print("-> {}".format(out))
    if args.verify:
        missing = []
        for text, name in loaded_sources:
            missing.extend((name, line) for line in verify(text, page))
        if missing:
            print("VERIFY: FAIL - {} source line(s) did not survive rendering".format(len(missing)))
            for name, line in missing[:10]:
                print("  - {}: {}".format(name, line[:110]))
            return 1
        print("VERIFY: PASS - every non-empty source line is present in the page")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
