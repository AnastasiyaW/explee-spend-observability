#!/usr/bin/env python3
"""Export a Claude Code session transcript to TRACE.md, verbatim.

The brief asks for "the REAL conversation - exported or copy-pasted as-is, every
message and every correction, verbatim", and warns that a hand-made trace tells
them nothing. So this tool changes the FORMAT of the transcript and nothing else.

    python export_trace.py <session.jsonl> -o TRACE.md [--max-result 2500]
    python export_trace.py --self-test

WHY THE FILTER IS WRITTEN THIS WAY (a bug worth remembering)
------------------------------------------------------------
The first version of this exporter skipped record types that look like editor
plumbing: attachment, queue-operation, bridge-session, last-prompt,
custom-title, atis-latch. Counting what survived gave 91 "user" records, which
looked plausible - until the human pointed out she had not written 91 messages.

Two separate errors were hiding under that number:

  1. `role: "user"` is not the human. Tool results come back under the same
     role, so 88 of those 91 records were machine output.
  2. Worse: a message the human sends WHILE a turn is running is not stored as
     a user record at all. It arrives as `attachment` with
     `attachment.type == "queued_command"`, carrying the text in
     `attachment.prompt` - and `attachment` was on the skip list. Six of the
     eight things she actually said would have been silently dropped, and the
     exported file would have looked complete.

A trace that quietly loses most of the human's words is a forgery by omission,
which is exactly what the brief says it can spot. So extraction is now driven by
WHERE HUMAN TEXT ACTUALLY LIVES, not by a denylist of record types.

WHAT IS REMOVED, AND NOTHING ELSE
  * `queue-operation` records - byte-identical duplicates of the `attachment`
    record for the same message; keeping them would print each mid-turn message
    two or three times.
  * `<system-reminder>` blocks injected into user turns by hooks - machine text
    the human never typed.
  * pure bookkeeping with no conversational content: bridge-session,
    last-prompt, custom-title, atis-latch.
  * Tool results longer than --max-result, so the file stays under the 5 MB
    upload cap. Every cut states how many characters were removed.

No message is dropped, reordered, softened or rewritten. Mistakes and dead ends
stay in; they are the point.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path

# Bookkeeping with no conversational content. `attachment` is deliberately NOT
# here: it is where mid-turn human messages live.
SKIP_TYPES = {"bridge-session", "last-prompt", "custom-title", "atis-latch",
              "queue-operation"}
REMINDER = re.compile(r"<system-reminder>.*?</system-reminder>\s*", re.S)
# The UI prefixes a queued message with a quote of what it was replying to.
ATTACH_PREFIX = re.compile(r"^<!--\s*attach\s*-->\s*", re.I)
# More machine text wearing the human's role: hook feedback and background-agent
# notifications arrive as user turns. They belong in the trace - they changed
# what happened next - but counting them as things the person said is a lie.
HARNESS_TEXT = re.compile(
    r"^\s*(?:Stop hook feedback:|<task-notification>|Caveat:|\[Request interrupted)", re.I)


def clean_user_text(text: str) -> str:
    """Drop hook-injected reminders; keep every character the human typed."""
    return REMINDER.sub("", text).strip()


def blocks_of(message) -> list:
    content = message.get("content")
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return content if isinstance(content, list) else []


def split_quoted_reply(prompt: str):
    """Separate the UI's quoted context from what the human actually wrote."""
    body = ATTACH_PREFIX.sub("", prompt).strip()
    quote_lines, own_lines, in_quote = [], [], True
    for line in body.splitlines():
        if in_quote and line.lstrip().startswith(">"):
            quote_lines.append(line.lstrip()[1:].strip())
        else:
            in_quote = False
            own_lines.append(line)
    return "\n".join(quote_lines).strip(), "\n".join(own_lines).strip()


def events(records):
    """Yield (timestamp, role, pieces) in transcript order, deduplicated."""
    seen_prompts = set()
    for record in records:
        kind = record.get("type")
        if kind in SKIP_TYPES:
            continue
        stamp = record.get("timestamp") or ""

        # A message the human sent while a turn was running.
        if kind == "attachment":
            attachment = record.get("attachment") or {}
            if attachment.get("type") != "queued_command":
                continue
            # The prompt is usually a string, but a message carrying an image or
            # a file arrives as a list of content blocks. Assuming the string
            # crashed this exporter on the very next session it was pointed at.
            prompt = attachment.get("prompt") or ""
            if isinstance(prompt, list):
                prompt = "\n".join(
                    block.get("text", "") for block in prompt
                    if isinstance(block, dict) and block.get("type") == "text")
            if not isinstance(prompt, str) or not prompt.strip() or prompt in seen_prompts:
                continue
            seen_prompts.add(prompt)
            quote, own = split_quoted_reply(prompt)
            pieces = []
            if quote:
                pieces.append("> _replying to:_ " + quote.replace("\n", "\n> "))
            if own:
                pieces.append(own)
            if pieces:
                # Machine text arrives on this path too - a background agent
                # finishing, a hook answering back. It belongs in the trace
                # because it changed what happened next, but labelling it as
                # something the person typed inflates the one count a reader
                # actually cares about: the existing header says eleven human
                # messages where ten is the truth.
                label = ("System (harness)" if HARNESS_TEXT.match(own or prompt)
                         else "User (sent mid-turn)")
                yield stamp, label, pieces
            continue

        message = record.get("message")
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        if role not in ("user", "assistant"):
            continue

        pieces = []
        label = "User" if role == "user" else "Assistant"
        for block in blocks_of(message):
            btype = block.get("type")
            if btype == "text":
                text = block.get("text") or ""
                if role == "user":
                    text = clean_user_text(text)
                    if HARNESS_TEXT.match(text):
                        label = "System (harness)"
                    if text and text not in seen_prompts:
                        seen_prompts.add(text)
                    elif text:
                        continue
                if text.strip():
                    pieces.append(text.rstrip())
            elif btype == "thinking":
                thought = (block.get("thinking") or "").strip()
                if thought:
                    pieces.append("<details><summary>reasoning</summary>\n\n"
                                  + thought + "\n\n</details>")
            elif btype == "tool_use":
                args = json.dumps(block.get("input") or {}, ensure_ascii=False, indent=1)
                pieces.append("**-> tool: `{}`**\n\n```json\n{}\n```".format(
                    block.get("name") or "?", args))
            elif btype == "tool_result":
                body = block.get("content")
                if isinstance(body, list):
                    body = "\n".join(b.get("text", "") for b in body if isinstance(b, dict))
                pieces.append(("**<- result**", str(body or "")))
        if pieces:
            yield stamp, label, pieces


def render(records, max_result: int):
    out, turn, human = [], 0, 0
    for stamp, role, pieces in events(records):
        turn += 1
        if role.startswith("User") and not any(isinstance(p, tuple) for p in pieces):
            human += 1
        rendered = []
        for piece in pieces:
            if isinstance(piece, tuple):                 # a tool result, truncatable
                label, body = piece
                if len(body) > max_result:
                    body = body[:max_result] + "\n... [{} more characters]".format(
                        len(body) - max_result)
                rendered.append("{}\n\n```\n{}\n```".format(label, body.rstrip()))
            else:
                rendered.append(piece)
        out.append("### {} · {}{}\n".format(turn, role, "  \n`" + stamp + "`" if stamp else ""))
        out.append("\n\n".join(rendered))
        out.append("\n---\n")
    return "\n".join(out), turn, human


HEADER = """# TRACE — {title}

Exported verbatim from the Claude Code session transcript by
[`export_trace.py`](export_trace.py). Every message, every tool call and every
correction appears in the order it happened, including the wrong turns.

Messages marked **User (sent mid-turn)** were typed while a turn was still
running; the editor stores them separately from ordinary turns, and an earlier
version of this exporter dropped all of them. The header of `export_trace.py`
records that bug in full.

Removed, and nothing else: duplicate `queue-operation` copies of mid-turn
messages, `<system-reminder>` blocks that hooks inject into user turns, and
editor bookkeeping records with no conversational content. Tool results longer
than {cap} characters are cut, and each cut states how many characters went.

Source: `{source}` · {turns} entries · {human} of them written by the human

---

"""


def export(path: Path, out: Path, title: str, max_result: int) -> int:
    records = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.strip():
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    body, turns, human = render(records, max_result)
    out.write_text(HEADER.format(title=title, cap=max_result, source=path.name,
                                 turns=turns, human=human) + body, encoding="utf-8")
    size = out.stat().st_size
    print("wrote {} - {} entries ({} human), {:.2f} MB".format(
        out, turns, human, size / 1_048_576))
    if size > 5 * 1_048_576:
        print("WARNING: over the 5 MB upload cap - lower --max-result", file=sys.stderr)
        return 1
    return 0


def self_test() -> int:
    failures = []
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        src = root / "s.jsonl"
        src.write_text("\n".join(json.dumps(r) for r in [
            {"type": "user", "timestamp": "T1", "message": {"role": "user", "content": [
                {"type": "text",
                 "text": "<system-reminder>hook noise</system-reminder>the opening question"}]}},
            {"type": "assistant", "timestamp": "T2", "message": {"role": "assistant", "content": [
                {"type": "thinking", "thinking": "private reasoning"},
                {"type": "text", "text": "I got this wrong at first"},
                {"type": "tool_use", "name": "Bash", "input": {"command": "ls"}}]}},
            {"type": "user", "timestamp": "T3", "message": {"role": "user", "content": [
                {"type": "tool_result", "content": "X" * 5000}]}},
            # the case the first version silently dropped:
            {"type": "queue-operation", "timestamp": "T4",
             "content": "<!-- attach --> > quoted bit\nSENT WHILE BUSY"},
            {"type": "attachment", "timestamp": "T4", "attachment": {
                "type": "queued_command",
                "prompt": "<!-- attach --> > quoted bit\nSENT WHILE BUSY"}},
            {"type": "attachment", "timestamp": "T4", "attachment": {
                "type": "queued_command",
                "prompt": "<!-- attach --> > quoted bit\nSENT WHILE BUSY"}},
            {"type": "user", "timestamp": "T5", "message": {"role": "user", "content": [
                {"type": "text", "text": "Stop hook feedback: write a handoff"}]}},
            {"type": "custom-title", "timestamp": "T6", "title": "PLUMBING"},
        ]), encoding="utf-8")
        out = root / "TRACE.md"
        export(src, out, "test", 100)
        text = out.read_text(encoding="utf-8")

        if "SENT WHILE BUSY" not in text:
            failures.append("a mid-turn human message was dropped - the exact bug this file exists for")
        if text.count("SENT WHILE BUSY") != 1:
            failures.append("mid-turn message printed {} times, expected once".format(
                text.count("SENT WHILE BUSY")))
        if "quoted bit" not in text:
            failures.append("the quoted context of a mid-turn reply was lost")
        if "PLUMBING" in text:
            failures.append("a bookkeeping record survived the filter")
        if "hook noise" in text:
            failures.append("a system-reminder survived the filter")
        if "the opening question" not in text:
            failures.append("the human's actual words were dropped")
        if "I got this wrong at first" not in text:
            failures.append("a mistake was dropped - that is falsification, not export")
        if "private reasoning" not in text:
            failures.append("reasoning block lost")
        if "4900 more characters" not in text:
            failures.append("truncation did not state how much it cut")
        if "Stop hook feedback" not in text:
            failures.append("harness feedback was dropped - it changed what happened next")
        if "System (harness)" not in text:
            failures.append("hook feedback was not labelled as harness text")
        if "2 of them written by the human" not in text:
            failures.append("human-message count is wrong: harness text counted as a person")
    if failures:
        print("SELF-TEST: FAIL")
        for f in failures:
            print("  - " + f)
        return 1
    print("SELF-TEST: PASS")
    return 0


def main(argv) -> int:
    ap = argparse.ArgumentParser(description="Export a session transcript to TRACE.md")
    ap.add_argument("session", nargs="?", help="path to the session .jsonl")
    ap.add_argument("-o", "--out", default="TRACE.md")
    ap.add_argument("--title", default="Task 1, spend observability")
    ap.add_argument("--max-result", type=int, default=2500)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)
    if args.self_test:
        return self_test()
    if not args.session:
        ap.error("session path is required unless --self-test")
    src = Path(args.session).expanduser()
    if not src.is_file():
        print("no such transcript: {}".format(src), file=sys.stderr)
        return 2
    return export(src, Path(args.out), args.title, args.max_result)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
