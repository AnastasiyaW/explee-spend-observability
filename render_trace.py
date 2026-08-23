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
import re
import sys
from pathlib import Path

HEADER = re.compile(r"^### (\d+) [·•] (.+?)\s*$")
STAMP = re.compile(r"^`(\d{4}-\d{2}-\d{2}T[0-9:.]+Z?)`\s*$")
FENCE = re.compile(r"^```(\w*)\s*$")
TOOL_CALL = re.compile(r"^\*\*-> tool: `(.+?)`\*\*", re.M)
TOOL_RESULT = re.compile(r"^\*\*<- result\*\*", re.M)


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
        return "tool_result" if TOOL_RESULT.search(body) else "human"
    return "tool_call" if TOOL_CALL.search(body) else "assistant"


def md_inline(text: str) -> str:
    """Escape first, then re-introduce only the marks the exporter itself writes."""
    out = html.escape(text, quote=False)
    out = re.sub(r"`([^`]+)`", r"<code>\1</code>", out)
    out = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", out)
    out = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", r'<a href="\2">\1</a>', out)
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
<style>
  :root{{
    --bg:#fbfbfa; --panel:#fff; --ink:#16150f; --muted:#6b6a60; --line:#e3e2dc;
    --accent:#2b5cd9; --human:#1a7f4b; --tool:#6b6a60; --grid:#efeee8; --code:#f5f4ef;
  }}
  @media (prefers-color-scheme: dark){{
    :root:not([data-theme="light"]){{
      --bg:#14140f; --panel:#1c1c17; --ink:#f0efe8; --muted:#9d9c91; --line:#2e2e27;
      --accent:#7ea2ff; --human:#4ec27f; --tool:#9d9c91; --grid:#26261f; --code:#111;
    }}
  }}
  *{{box-sizing:border-box}}
  body{{margin:0;background:var(--bg);color:var(--ink);
    font:15px/1.62 ui-sans-serif,system-ui,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}}
  .shell{{display:grid;grid-template-columns:270px minmax(0,1fr);gap:26px;
    max-width:1220px;margin:0 auto;padding:26px 18px 80px}}
  @media (max-width:900px){{ .shell{{grid-template-columns:1fr}} .rail{{position:static;max-height:none}} }}
  .rail{{position:sticky;top:20px;align-self:start;max-height:88vh;overflow:auto;
    border:1px solid var(--line);border-radius:11px;background:var(--panel);padding:12px 6px}}
  .rail h3{{font-size:11px;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);
    margin:4px 10px 8px;font-weight:600}}
  .rail a{{display:block;color:inherit;text-decoration:none;font-size:12.5px;line-height:1.45;
    padding:7px 10px;border-radius:7px;border-left:2px solid transparent}}
  .rail a:hover{{background:var(--grid);border-left-color:var(--human)}}
  .rail a b{{display:block;font-size:10.5px;color:var(--muted);font-weight:600;
    letter-spacing:.05em;text-transform:uppercase}}
  h1{{font-size:23px;margin:0 0 6px;letter-spacing:-.02em}}
  .lede{{color:var(--muted);font-size:13.5px;margin:0 0 8px;max-width:70ch}}
  .lede a{{color:var(--accent)}}
  .facts{{display:flex;gap:16px;flex-wrap:wrap;font-size:12.5px;color:var(--muted);
    border:1px solid var(--line);border-radius:10px;background:var(--panel);
    padding:10px 13px;margin:0 0 20px}}
  .facts b{{color:var(--ink)}}
  .msg{{border:1px solid var(--line);border-radius:11px;background:var(--panel);
    padding:13px 16px;margin:0 0 11px;scroll-margin-top:16px}}
  .msg.human{{border-left:3px solid var(--human);background:var(--panel)}}
  .msg.assistant{{border-left:3px solid var(--accent)}}
  .msg.tool_call, .msg.tool_result, .msg.system{{border-left:3px solid var(--line)}}
  .who{{display:flex;gap:10px;align-items:baseline;font-size:11px;text-transform:uppercase;
    letter-spacing:.07em;color:var(--muted);margin:0 0 7px}}
  .who .n{{font-weight:700;color:var(--ink)}}
  .who .role{{font-weight:650}}
  .msg.human .who .role{{color:var(--human)}}
  .msg.assistant .who .role{{color:var(--accent)}}
  .who time{{margin-left:auto;font:11px ui-monospace,Consolas,monospace;text-transform:none}}
  .msg p{{margin:0 0 9px}} .msg p:last-child{{margin-bottom:0}}
  pre{{background:var(--code);border:1px solid var(--line);border-radius:8px;padding:10px 12px;
    overflow-x:auto;margin:0 0 9px}}
  pre code{{font:12px/1.55 ui-monospace,"Cascadia Code",Consolas,monospace;background:none;padding:0}}
  code{{font:12.5px ui-monospace,"Cascadia Code",Consolas,monospace;background:var(--code);
    border-radius:4px;padding:1px 4px}}
  blockquote{{margin:0 0 9px;padding-left:11px;border-left:2px solid var(--line);color:var(--muted)}}
  ul{{margin:0 0 9px;padding-left:20px}}
  details summary{{cursor:pointer;color:var(--muted);font-size:12.5px;list-style:none}}
  details summary::-webkit-details-marker{{display:none}}
  details summary::before{{content:"\\25b8 ";color:var(--muted)}}
  details[open] summary::before{{content:"\\25be "}}
  details[open] summary{{margin-bottom:8px}}
  .peek{{font:12px ui-monospace,Consolas,monospace;color:var(--muted)}}
  footer{{margin-top:26px;color:var(--muted);font-size:12.5px;line-height:1.7}}
  footer a{{color:var(--accent)}}
  a.back{{color:var(--accent);text-decoration:none;font-size:13px}}
  .langswitch{{position:fixed;top:12px;right:14px;display:flex;z-index:5;
    border:1px solid var(--line);border-radius:20px;overflow:hidden;background:var(--panel)}}
  .langswitch button{{border:0;background:transparent;color:var(--muted);cursor:pointer;
    font:600 11px/1 ui-sans-serif,system-ui,sans-serif;letter-spacing:.06em;padding:6px 10px}}
  .langswitch button[aria-current="true"]{{background:var(--accent);color:#fff}}
</style>
<script src="i18n.js"></script>
</head>
<body>
<div class="shell">
  <nav class="rail">
    <h3 data-i18n="trace.rail">What the human said</h3>
{rail}
  </nav>
  <main>
    <p><a class="back" href="./" data-i18n="spend.back">&larr; all three tasks</a></p>
    <h1 data-i18n="trace.h1">Agent trace &middot; Task 1</h1>
    <p class="lede" data-i18n="trace.lede">{lede}</p>
    <div class="facts">
      <span><b>{total}</b> <span data-i18n="trace.f.total">messages</span></span>
      <span><b>{humans}</b> <span data-i18n="trace.f.human">from the human</span></span>
      <span><b>{assistants}</b> <span data-i18n="trace.f.agent">from the agent</span></span>
      <span><b>{calls}</b> <span data-i18n="trace.f.calls">tool calls</span></span>
      <span><b>{results}</b> <span data-i18n="trace.f.results">tool results</span></span>
    </div>
{body}
    <footer data-i18n="trace.foot">{foot}</footer>
  </main>
</div>
</body>
</html>
"""


def render(markdown_text: str, source_name: str) -> str:
    preamble, blocks = split_blocks(markdown_text)
    kinds = [classify(b) for b in blocks]
    rail, body = [], []
    for block, kind in zip(blocks, kinds):
        anchor = "m{}".format(block["n"])
        label, hint = LABEL[kind]
        stamp = '<time>{}</time>'.format(html.escape(block["ts"])) if block["ts"] else ""
        head = ('<div class="who"><span class="n">{}</span>'
                '<span class="role">{}</span><span>{}</span>{}</div>').format(
                    block["n"], label, hint, stamp)
        content = md_body(block["lines"])
        if kind in ("tool_result", "tool_call", "system"):
            peek = html.escape(first_line(block)[:110], quote=False)
            content = ("<details><summary><span class=\"peek\">{}</span></summary>{}</details>"
                       .format(peek or label, content))
        body.append('<section class="msg {}" id="{}">{}{}</section>'.format(kind, anchor, head, content))
        if kind == "human":
            rail.append('    <a href="#{}"><b>{}</b>{}</a>'.format(
                anchor, block["n"], html.escape(first_line(block)[:96], quote=False)))

    lede = (
        'The real session, verbatim. This page only changes how it is laid out: nothing is '
        'removed, reordered or reworded here. The transcript files tool results under the same '
        '"user" role as the person, so they are labelled apart and folded shut - that is the '
        'only reason this reads more easily than '
        '<a href="https://github.com/AnastasiyaW/explee-spend-observability/blob/main/{src}">'
        'the raw file</a>, which stays the artefact of record.'
    ).format(src=html.escape(source_name))
    foot = (
        'Generated from <code>{src}</code> by '
        '<a href="https://github.com/AnastasiyaW/explee-spend-observability/blob/main/render_trace.py">'
        'render_trace.py</a>, which is in the repository and can be re-run against the same input. '
        'The export itself, and the one bug that nearly lost most of the human’s messages, are '
        'documented in the header of <code>export_trace.py</code>.'
    ).format(src=html.escape(source_name))
    if preamble:
        foot += "<br><br>" + md_body(preamble.splitlines())
    return PAGE.format(
        rail="\n".join(rail) or '    <a href="#">no human messages found</a>',
        body="\n".join(body),
        lede=lede, foot=foot,
        total=len(blocks),
        humans=kinds.count("human"),
        assistants=kinds.count("assistant"),
        calls=kinds.count("tool_call"),
        results=kinds.count("tool_result"),
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
    page = render(sample, "T.md")
    # The whole promise of this script is that it drops nothing.
    for needle in ("Hello", "welcome", "ls -la", "total 0", "Done, see"):
        if needle not in page:
            failures.append("content lost in rendering: " + needle)
    if "<b>&</b>" in page:
        failures.append("raw markup from the transcript reached the page unescaped")
    if "&lt;b&gt;" not in page:
        failures.append("markup in a message was not escaped into visible text")
    if page.count('class="msg') != 4:
        failures.append("expected one section per message, got {}".format(page.count('class="msg')))
    # A tool result must be folded, a human message must not be.
    human_section = page.split('id="m1"')[1].split("</section>")[0]
    if "<details>" in human_section:
        failures.append("a human message was folded shut")
    if "<details>" not in page.split('id="m3"')[1].split("</section>")[0]:
        failures.append("a tool result was not folded")
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
        forms = {_marks(line), _marks(re.sub(r"\[([^\]]+)\]\([^)\s]+\)", r"\1", line))}
        forms = {f for f in forms if len(f) >= 3}
        if not forms:
            continue
        if not any(f in haystack for f in forms):
            missing.append(raw.strip())
    return sorted(set(missing), key=missing.index)


def main(argv) -> int:
    ap = argparse.ArgumentParser(description="Render a verbatim trace as one HTML page")
    ap.add_argument("source", nargs="?", help="the TRACE markdown produced by export_trace.py")
    ap.add_argument("-o", "--out", default="docs/trace.html")
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--verify", action="store_true",
                    help="after rendering, prove every source line survived")
    args = ap.parse_args(argv)
    if args.self_test:
        return self_test()
    if not args.source:
        ap.error("a source file is required")
    src = Path(args.source)
    text = src.read_text(encoding="utf-8")
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    page = render(text, src.name)
    out.write_text(page, encoding="utf-8")
    _, blocks = split_blocks(text)
    kinds = [classify(b) for b in blocks]
    print("{} -> {}  ({} messages, {} from the human)".format(
        src, out, len(blocks), kinds.count("human")))
    if args.verify:
        missing = verify(text, page)
        if missing:
            print("VERIFY: FAIL - {} source line(s) did not survive rendering".format(len(missing)))
            for line in missing[:10]:
                print("  - " + line[:120])
            return 1
        print("VERIFY: PASS - every non-empty source line is present in the page")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
