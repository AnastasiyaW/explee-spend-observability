# PROBLEMS

Open defects in this deliverable. An entry stays OPEN only with a stated reason.

## 2026-08-23 09:35 — README names our hosting vendor

**Status**: CLOSED 2026-08-23 18:40 — the line now reads "a small VPS"; verified by
`grep -n "How it runs" -A3 README.md`, and the vendor name appears nowhere in the
tracked tree. The entry outlived its fix by nine hours, which is its own small lesson:
a tracker is only load-bearing if closing an item is part of doing the work.
**Where**: `README.md`, the "How it runs" section, the line that named the host

Our own outbound gate flagged it: the vendor's name is one of this machine's ssh host
aliases, so `submission_scan.py` treats it as a private identifier. It is a hosting
brand rather than a credential, so the exposure is small — but the fix costs nothing
and the rule says redact by substitution.

**Fix**: replace the vendor name with "a small VPS". Do not delete the section. And do
not name it in this ticket either: a redaction ticket that quotes the string three times
publishes it three times, which is what this entry did until it was closed.

**Why not already done**: two independent verifier agents are reading `README.md` right
now. Mutating a file under a running audit is a known way to get a report about a state
that no longer exists. Apply immediately after they return.

## 2026-08-23 09:33 — pre-push scan runs with one agent instead of two

**Status**: OPEN — missing-dep

Every `git push` from this machine prints:

```
[pre-push] Agent B: claude CLI found (...\claude.exe) but call failed:
Failed to authenticate: OAuth session expired and could not be refreshed
[pre-push] ⚠️  Agent B unavailable. Falling back to Agent A only.
```

The public-repo secret scan is designed as two independent agents; it is currently
running as one. Agent A passed on every push here, and this repository contains no
credentials, so nothing leaked — but the second opinion that makes the gate a gate is
absent.

**Fix**: re-authenticate the `claude` CLI on this machine, then confirm a push prints
Agent B's verdict. Belongs to the machine's harness, not to this deliverable.
