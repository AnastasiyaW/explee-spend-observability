#!/usr/bin/env python3
"""Export a Codex (OpenAI) session rollout to TRACE markdown, verbatim.

Sibling of `export_trace.py`, which does the same job for a Claude Code
transcript. Same brief, same rule: change the FORMAT of the transcript and
nothing else. Same output shape too, because a renderer already parses it -
`### N - Role`, the backticked timestamp under it, a `-> tool:` line for a call
and a `<- result` line for what came back.

    python export_codex_trace.py <rollout.jsonl> -o TRACE.md [--max-result 2500]
    python export_codex_trace.py --self-test

WHY THE FILTER IS WRITTEN THIS WAY
----------------------------------
`export_trace.py` records a bug worth repeating: it counted 91 "user" records
when the human had written eight, because tool results wear the human's role
AND because messages typed while a turn was running were stored under a record
type that was on the skip list. Both halves of that mistake have a twin in the
Codex schema, and both were checked for here rather than assumed away:

  1. ROLE IS NOT AUTHORSHIP. `response_item / message / role="user"` carries
     69 records in the session this was written for. Eleven are `<heartbeat>`
     wake-ups from an automation the human scheduled and one is a 47 KB bundle
     of `<recommended_plugins>`, an AGENTS.md dump and `<environment_context>`;
     that leaves 57. Eight of those 57 have an `<in-app-browser-context>`
     block - ambient state that literally says "not part of the user's
     request" - wrapped around the sentence the person did type, so the block
     comes out and the sentence stays. Trusting the role would have reported
     69 human messages; counting the tool results that also arrive under it,
     1101 more.

  2. THE SAME MESSAGE IS WRITTEN TWICE, IN TWO SHAPES. Codex logs each user
     message as both `event_msg/user_message` and `response_item/message`,
     each assistant message as both `event_msg/agent_message` and
     `response_item/message`, and each thought as both
     `event_msg/agent_reasoning` and the `summary` of `response_item/reasoning`.
     Printing the file as it lies would double every word.

     Choosing which copy to keep is not arbitrary. For 12 of the 207 assistant
     messages the two copies DIFFER: the `event_msg` version is the shorter
     one, with `<oai-mem-cit...>` citation markup stripped. So the
     `response_item` copy is kept everywhere and the `event_msg` copy dropped -
     never the reverse. For user messages the check was run the other way
     round: every one of the 68 `event_msg/user_message` texts was confirmed
     present in the `response_item` corpus before that copy was dropped, so no
     human word rides only on the discarded record. That check is the reason
     this exporter can state a count instead of hoping for one.

WHAT IS REMOVED, AND NOTHING ELSE
  * Duplicate copies of a message already printed from another record type:
    `event_msg/user_message`, `event_msg/agent_message`,
    `event_msg/agent_reasoning`, and `task_complete.last_agent_message`.
  * `<in-app-browser-context>` blocks - ambient UI state the app injects into
    a user turn, self-described as "not part of the user's request". The
    Codex equivalent of a `<system-reminder>`. The human's own sentence in the
    same record is kept.
  * The `# Files mentioned by the user:` framing the app wraps around an
    attachment. The attached path is kept as a one-line note; the human's
    request under `## My request for Codex:` is kept verbatim.
  * `reasoning.encrypted_content` - opaque ciphertext, no readable content.
    The readable `summary` of the same record is kept.
  * Base64 image payloads, replaced by a note stating how many characters went.
  * Pure bookkeeping with no conversational content: `session_meta` (55 copies
    of one session's own system prompt, 2.6 MB), `world_state`, `turn_context`,
    `compacted` (replays history already printed above it), `token_count`,
    `task_started`, `thread_settings_applied`,
    `inter_agent_communication_metadata`.
  * Text longer than --max-result, so the file stays under the 5 MB upload cap.
    The cap applies to tool inputs, tool results and harness injections - never
    to a human or assistant message. Every cut states how many characters went.

Machine text that DROVE the conversation is kept, not dropped, and labelled so
it cannot be read as something a person said: automation heartbeats, harness
injections, sub-agent messages and context-compaction markers. Removing them
would make the assistant's replies look unprompted, which is a lie of a
different kind.

No message is dropped, reordered, softened or rewritten. Mistakes, typos and
dead ends stay in; they are the point.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path

# Record types that carry no conversational content of their own.
SKIP_RECORD_TYPES = {
    "session_meta", "world_state", "turn_context", "compacted",
    "inter_agent_communication_metadata",
}
# event_msg payload types that duplicate a response_item, or are pure telemetry.
SKIP_EVENTS = {
    "user_message",        # duplicate of response_item/message role=user
    "agent_message",       # duplicate of response_item/message role=assistant
    "agent_reasoning",     # duplicate of response_item/reasoning .summary
    "task_complete",       # .last_agent_message duplicates the message above it
    "task_started", "token_count", "thread_settings_applied",
}

# Envelopes the app injects into a user-role record. If a record is nothing but
# these, no human typed it.
MACHINE_ENVELOPES = (
    "recommended_plugins", "user_instructions", "environment_context",
    "skills_instructions", "apps_instructions", "plugins_instructions",
    "app-context", "permissions", "collaboration_mode", "multi_agent_mode",
    "model_switch", "in-app-browser-context", "INSTRUCTIONS",
)
# The app prints this header above the project's AGENTS.md before injecting it.
AGENTS_HDR = re.compile(r"^[ \t]*#[ \t]*AGENTS\.md instructions for .*$", re.M)
HEARTBEAT = re.compile(r"<heartbeat>.*?</heartbeat>", re.S)
AMBIENT = re.compile(r"<in-app-browser-context\b.*?</in-app-browser-context>\s*", re.S)
FILES_HDR = re.compile(
    r"^[ \t]*#[ \t]*Files mentioned by the user:[ \t]*\n(?P<body>(?:.*?\n)*?)"
    r"(?=^[ \t]*##[ \t]*My request for Codex:|\Z)", re.M)
REQUEST_MARK = re.compile(r"^[ \t]*##[ \t]*My request for Codex:[ \t]*\n?", re.M)
IMAGE_OPEN = re.compile(r"^<image name=.*?path=\"(?P<path>[^\"]*)\".*?>$", re.M)
IMAGE_CLOSE = re.compile(r"^</image>$", re.M)
FILE_LINE = re.compile(r"^[ \t]*##[ \t]*(?P<name>[^:\n]+):[ \t]*(?P<path>.+)$", re.M)

TOOL_CALL_LINE = "**-> tool: `{}`**"
RESULT_LINE = "**<- result**"


def strip_envelope(text: str, tag: str) -> str:
    """Remove one `<tag>...</tag>` block, or tag-to-end when it never closes."""
    pattern = re.compile(r"<{0}\b.*?</{0}>\s*".format(re.escape(tag)), re.S)
    out = pattern.sub("", text)
    if "<" + tag in out:
        out = re.sub(r"<{0}\b.*\Z".format(re.escape(tag)), "", out, flags=re.S)
    return out


def human_part(text: str):
    """Split a user-role record into (what the human typed, machine notes).

    Ambient UI state, attachment framing and injected instruction envelopes come
    out; every character the person typed stays in.
    """
    notes = []
    body = AMBIENT.sub("", text)
    if body != text:
        notes.append("_[ambient in-app-browser state injected by the app, removed]_")
    match = FILES_HDR.search(body)
    if match:
        for hit in FILE_LINE.finditer(match.group("body")):
            notes.append("_[attached: {}]_".format(hit.group("path").strip()))
        body = body[:match.start()] + body[match.end():]
    for hit in IMAGE_OPEN.finditer(body):
        notes.append("_[attached image: {}]_".format(hit.group("path")))
    body = IMAGE_OPEN.sub("", body)
    body = IMAGE_CLOSE.sub("", body)
    body = REQUEST_MARK.sub("", body)
    for tag in MACHINE_ENVELOPES:
        if "<" + tag in body:
            body = strip_envelope(body, tag)
    body = AGENTS_HDR.sub("", body)
    body = HEARTBEAT.sub("", body)
    return body.strip(), notes


def user_record(payload):
    """(label, pieces) for one `response_item / message / role=user`."""
    raw, images = [], []
    for block in payload.get("content") or []:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "input_text":
            raw.append(block.get("text") or "")
        elif block.get("type") == "input_image":
            images.append(len(block.get("image_url") or ""))
    text = "\n".join(raw)
    typed, notes = human_part(text)
    for size in images:
        notes.append("_[image data omitted: {} characters of base64 data URL]_".format(size))

    if typed:
        return "User", notes + [typed]
    if HEARTBEAT.search(text):
        return "System (automation heartbeat)", notes + [("keep", text.strip())]
    return "System (harness injection)", notes + [("cut", text.strip())]


def tool_output_text(output) -> str:
    if isinstance(output, list):
        return "\n".join(b.get("text", "") for b in output if isinstance(b, dict))
    return "" if output is None else str(output)


def events(records):
    """Yield (timestamp, role, pieces) in file order.

    A piece is a string (printed as-is), a ("cut"|"keep", body) tuple where
    "cut" may be shortened by --max-result and "keep" never is, or a
    (heading, (mode, body)) pair for a labelled code block.
    """
    for record in records:
        kind = record.get("type")
        if kind in SKIP_RECORD_TYPES:
            continue
        stamp = record.get("timestamp") or ""
        payload = record.get("payload")
        if not isinstance(payload, dict):
            continue
        ptype = payload.get("type")

        if kind == "event_msg":
            if ptype in SKIP_EVENTS:
                continue
            if ptype == "context_compacted":
                yield stamp, "System (context compacted)", [
                    "The harness compacted the conversation here. The replaced history is "
                    "already printed above; the `compacted` record that replays it is not "
                    "printed again."]
            elif ptype == "sub_agent_activity":
                yield stamp, "System (sub-agent)", ["`{}` {} (thread `{}`)".format(
                    payload.get("agent_path") or "?", payload.get("kind") or "?",
                    payload.get("agent_thread_id") or "?")]
            elif ptype == "patch_apply_end":
                body = (payload.get("stdout") or "") + (payload.get("stderr") or "")
                changes = payload.get("changes") or {}
                if changes:
                    body += "\n" + json.dumps(changes, ensure_ascii=False, indent=1)
                yield stamp, "User (tool result)", [(
                    RESULT_LINE + " patch apply, success={}".format(payload.get("success")),
                    ("cut", body))]
            elif ptype == "web_search_end":
                yield stamp, "Assistant", [(
                    TOOL_CALL_LINE.format("web_search"),
                    ("cut", json.dumps(payload.get("action") or payload.get("query") or {},
                                       ensure_ascii=False, indent=1)))]
                yield stamp, "User (tool result)", [(RESULT_LINE, ("cut", json.dumps(
                    payload.get("results") or [], ensure_ascii=False, indent=1)))]
            elif ptype == "mcp_tool_call_end":
                inv = payload.get("invocation") or {}
                yield stamp, "Assistant", [(
                    TOOL_CALL_LINE.format("mcp:{}/{}".format(
                        inv.get("server") or "?", inv.get("tool") or "?")),
                    ("cut", json.dumps(inv.get("arguments") or {}, ensure_ascii=False, indent=1)))]
                yield stamp, "User (tool result)", [(RESULT_LINE, ("cut", json.dumps(
                    payload.get("result"), ensure_ascii=False, indent=1)))]
            continue

        if kind != "response_item":
            continue

        if ptype == "message":
            role = payload.get("role")
            if role == "user":
                label, pieces = user_record(payload)
                if pieces:
                    yield stamp, label, pieces
            elif role == "assistant":
                text = "\n".join((b.get("text") or "") for b in payload.get("content") or []
                                 if isinstance(b, dict)).rstrip()
                if text.strip():
                    yield stamp, "Assistant", [text]
            elif role == "developer":
                text = "\n".join((b.get("text") or "") for b in payload.get("content") or []
                                 if isinstance(b, dict)).rstrip()
                if text.strip():
                    yield stamp, "System (harness injection)", [("cut", text)]
        elif ptype == "reasoning":
            thought = "\n\n".join((s.get("text") or "").strip()
                                  for s in payload.get("summary") or []
                                  if (s.get("text") or "").strip())
            if thought:
                yield stamp, "Assistant", [
                    "<details><summary>reasoning</summary>\n\n" + thought + "\n\n</details>"]
        elif ptype == "custom_tool_call":
            yield stamp, "Assistant", [(TOOL_CALL_LINE.format(payload.get("name") or "?"),
                                        ("cut", payload.get("input") or ""))]
        elif ptype == "function_call":
            yield stamp, "Assistant", [(TOOL_CALL_LINE.format(payload.get("name") or "?"),
                                        ("cut", payload.get("arguments") or ""))]
        elif ptype in ("custom_tool_call_output", "function_call_output"):
            yield stamp, "User (tool result)", [
                (RESULT_LINE, ("cut", tool_output_text(payload.get("output"))))]
        elif ptype == "agent_message":
            text = "\n".join((b.get("text") or "") for b in payload.get("content") or []
                             if isinstance(b, dict)).rstrip()
            if text.strip():
                yield stamp, "Assistant (sub-agent {})".format(
                    payload.get("author") or "?"), [text]


def render(records, max_result: int):
    out, turn, human = [], 0, 0
    for stamp, role, pieces in events(records):
        turn += 1
        if role == "User":
            human += 1
        rendered = []
        for piece in pieces:
            heading = None
            if isinstance(piece, tuple) and len(piece) == 2 and isinstance(piece[1], tuple):
                heading, piece = piece
            if isinstance(piece, tuple):
                mode, body = piece
                body = body or ""
                if mode == "cut" and len(body) > max_result:
                    body = body[:max_result] + "\n... [{} more characters]".format(
                        len(body) - max_result)
                block = "```\n{}\n```".format(body.rstrip())
                rendered.append(heading + "\n\n" + block if heading else block)
            else:
                rendered.append(piece)
        out.append("### {} · {}{}\n".format(turn, role, "  \n`" + stamp + "`" if stamp else ""))
        out.append("\n\n".join(rendered))
        out.append("\n---\n")
    return "\n".join(out), turn, human


HEADER = """# TRACE — {title}

Exported verbatim from the Codex session rollout by
[`export_codex_trace.py`](export_codex_trace.py). Every message, every tool
call and every correction appears in the order it happened, including the wrong
turns. `TRACE-task1.redacted.md` is the Claude Code half of the same work; this
is the Codex half.

**Role is not authorship.** Codex files tool results, automation wake-ups and
injected app state under the user's role. Only entries labelled exactly
**User** were typed by a person. **User (tool result)** is machine output,
**System (automation heartbeat)** is a scheduled wake-up the human configured
but did not type, **System (harness injection)** is instruction text the app
adds, and **Assistant (sub-agent ...)** is a report from a spawned agent.

Removed, and nothing else: the duplicate `event_msg` copy of each message
already printed from its `response_item` (the `response_item` copy is the
longer one wherever the two differ), `<in-app-browser-context>` blocks the app
injects into a user turn, the `# Files mentioned by the user:` framing around
an attachment, the opaque `reasoning.encrypted_content` ciphertext, base64
image payloads, and bookkeeping records with no conversational content. Text
longer than {cap} characters is cut - tool inputs, tool results and harness
injections only, never a human or assistant message - and each cut states how
many characters went.

Source: `{source}` · {turns} entries · {human} of them written by the human

---

"""


def load(path: Path):
    records = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def export(path: Path, out: Path, title: str, max_result: int) -> int:
    body, turns, human = render(load(path), max_result)
    text = HEADER.format(title=title, cap=max_result, source=path.name,
                         turns=turns, human=human) + body
    # newline="" or Windows turns a CRLF the human's editor put in the transcript
    # into CR CR LF. 7045 of those were produced before this was noticed.
    with out.open("w", encoding="utf-8", newline="") as handle:
        handle.write(text)
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
            {"type": "session_meta", "timestamp": "T0",
             "payload": {"session_id": "s", "base_instructions": "SYSTEM PROMPT BLOB"}},
            # role=user, but nobody typed it: three envelopes in three blocks, the
            # middle one an AGENTS.md dump that sits OUTSIDE any <...> envelope
            {"type": "response_item", "timestamp": "T1", "payload": {
                "type": "message", "role": "user", "content": [
                    {"type": "input_text",
                     "text": "<recommended_plugins>PLUGIN NOISE</recommended_plugins>"},
                    {"type": "input_text",
                     "text": "# AGENTS.md instructions for C:/repo\n\n<INSTRUCTIONS>\n"
                             "PROJECT RULES BLOB\n</INSTRUCTIONS>"},
                    {"type": "input_text",
                     "text": "<environment_context><cwd>C:/repo</cwd></environment_context>"}]}},
            # the real opening message, logged twice in two shapes
            {"type": "response_item", "timestamp": "T2", "payload": {
                "type": "message", "role": "user", "content": [
                    {"type": "input_text", "text": "the opening question"}]}},
            {"type": "event_msg", "timestamp": "T2",
             "payload": {"type": "user_message", "message": "the opening question"}},
            {"type": "response_item", "timestamp": "T3", "payload": {
                "type": "reasoning",
                "summary": [{"type": "summary_text", "text": "private reasoning"}],
                "encrypted_content": "CIPHERTEXTBLOB"}},
            {"type": "event_msg", "timestamp": "T3",
             "payload": {"type": "agent_reasoning", "text": "private reasoning"}},
            # assistant message: the event copy is the SHORTER one
            {"type": "event_msg", "timestamp": "T4",
             "payload": {"type": "agent_message", "message": "I got this wrong at first"}},
            {"type": "response_item", "timestamp": "T4", "payload": {
                "type": "message", "role": "assistant", "content": [
                    {"type": "output_text",
                     "text": "I got this wrong at first<oai-mem-cit id=7 />"}]}},
            {"type": "response_item", "timestamp": "T5", "payload": {
                "type": "custom_tool_call", "name": "exec", "input": "ls"}},
            {"type": "response_item", "timestamp": "T6", "payload": {
                "type": "custom_tool_call_output", "output": "X" * 5000}},
            # automation wake-up wearing the human's role
            {"type": "response_item", "timestamp": "T7", "payload": {
                "type": "message", "role": "user", "content": [
                    {"type": "input_text",
                     "text": "<heartbeat>\n<automation_id>a-10</automation_id>\n</heartbeat>"}]}},
            # ambient UI state injected NEXT TO a real sentence
            {"type": "response_item", "timestamp": "T8", "payload": {
                "type": "message", "role": "user", "content": [
                    {"type": "input_text",
                     "text": "\n<in-app-browser-context source=\"ambient-ui-state\">\n"
                             "AMBIENT NOISE\n</in-app-browser-context>\n\n"
                             "## My request for Codex:\nвот же сайт\n"}]}},
            # pasted screenshot: framing is machine, the request is not
            {"type": "response_item", "timestamp": "T9", "payload": {
                "type": "message", "role": "user", "content": [
                    {"type": "input_text",
                     "text": "\n# Files mentioned by the user:\n\n## shot.png: D:/tmp/shot.png\n\n"
                             "## My request for Codex:\nSENT WITH A SCREENSHOT\n"},
                    {"type": "input_text",
                     "text": "<image name=[Image #1] path=\"D:/tmp/shot.png\">"},
                    {"type": "input_image", "image_url": "data:image/png;base64," + "A" * 900},
                    {"type": "input_text", "text": "</image>"}]}},
            # the app stores some messages with CRLF; Windows text mode would make
            # that CR CR LF on the way out
            {"type": "response_item", "timestamp": "TA0", "payload": {
                "type": "message", "role": "user", "content": [
                    {"type": "input_text", "text": "line one\r\nline two"}]}},
            {"type": "response_item", "timestamp": "TA", "payload": {
                "type": "agent_message", "author": "/root/reviewer", "content": [
                    {"type": "input_text", "text": "FINDING: sub-agent said this"}]}},
            {"type": "event_msg", "timestamp": "TB", "payload": {
                "type": "task_complete", "last_agent_message": "I got this wrong at first"}},
            {"type": "event_msg", "timestamp": "TC", "payload": {"type": "token_count"}},
            {"type": "world_state", "timestamp": "TD", "payload": {"state": "WORLD BLOB"}},
        ]), encoding="utf-8")
        out = root / "TRACE.md"
        export(src, out, "test", 100)
        raw = out.read_bytes()
        text = raw.decode("utf-8")

        def want(needle, why):
            if needle not in text:
                failures.append(why)

        want("the opening question", "the human's actual words were dropped")
        if text.count("the opening question") != 1:
            failures.append("the human's message printed {} times - the event_msg copy was not "
                            "deduplicated".format(text.count("the opening question")))
        want("I got this wrong at first<oai-mem-cit",
             "the LONGER assistant copy was dropped in favour of the truncated event_msg one")
        if text.count("I got this wrong at first") != 1:
            failures.append("assistant message printed {} times".format(
                text.count("I got this wrong at first")))
        want("вот же сайт",
             "a human sentence sharing a record with ambient UI state was dropped")
        if "AMBIENT NOISE" in text:
            failures.append("injected ambient UI state survived the filter")
        want("SENT WITH A SCREENSHOT", "a human message that carried an attachment was dropped")
        want("[attached image: D:/tmp/shot.png]", "the attachment itself went unmentioned")
        want("characters of base64 data URL",
             "base64 image payload removed without stating the size")
        want("automation heartbeat", "an automation wake-up was not labelled as machine text")
        want("a-10", "the automation wake-up body was dropped - the reply would look unprompted")
        want("private reasoning", "reasoning summary lost")
        if "CIPHERTEXTBLOB" in text:
            failures.append("opaque encrypted_content was printed")
        if text.count("private reasoning") != 1:
            failures.append("reasoning printed twice - the event_msg copy was not deduplicated")
        want("FINDING: sub-agent said this", "a sub-agent report was dropped")
        want("4900 more characters", "truncation did not state how much it cut")
        if "SYSTEM PROMPT BLOB" in text:
            failures.append("bookkeeping record survived the filter: session_meta")
        if "WORLD BLOB" in text:
            failures.append("bookkeeping record survived the filter: world_state")
        if "PLUGIN NOISE" not in text:
            failures.append("an injected envelope was deleted outright instead of being "
                            "labelled as harness text")
        else:
            head = text.split("PLUGIN NOISE")[0].rsplit("### ", 1)[-1].splitlines()[0]
            if not head.startswith("1 · System (harness injection)"):
                failures.append("the injected plugins/AGENTS.md bundle was filed as a person's "
                                "message: " + head)
        # Three records in the fixture were typed by a person; three more wear the
        # user's role without a person behind them (plugins bundle, heartbeat, tool
        # result), and the tool result is a fourth.
        if "System (harness injection)" not in text:
            failures.append("the injected plugins bundle was counted as a person's message")
        if "User (tool result)" not in text:
            failures.append("a tool result was not separated from the human's role")
        if b"line one\r\nline two" not in raw:
            failures.append("a CRLF the app stored in a human message was rewritten on the way "
                            "out (Windows text mode turns CRLF into CR CR LF)")
        if b"\r\r\n" in raw:
            failures.append("output contains CR CR LF - newline translation corrupted the text")
        found = re.search(r"· (\d+) of them written by the human", text)
        if not found or found.group(1) != "4":
            failures.append("human count is {}, expected 4 - machine records wearing the user "
                            "role were counted as a person".format(
                                found.group(1) if found else "missing"))
    if failures:
        print("SELF-TEST: FAIL")
        for line in failures:
            print("  - " + line)
        return 1
    print("SELF-TEST: PASS")
    return 0


def main(argv) -> int:
    parser = argparse.ArgumentParser(description="Export a Codex rollout to TRACE markdown")
    parser.add_argument("session", nargs="?", help="path to the rollout .jsonl")
    parser.add_argument("-o", "--out", default="TRACE-codex.md")
    parser.add_argument("--title", default="Task 1 and Task 2, the Codex half")
    parser.add_argument("--max-result", type=int, default=2500)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    if args.self_test:
        return self_test()
    if not args.session:
        parser.error("session path is required unless --self-test")
    src = Path(args.session).expanduser()
    if not src.is_file():
        print("no such rollout: {}".format(src), file=sys.stderr)
        return 2
    return export(src, Path(args.out), args.title, args.max_result)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
