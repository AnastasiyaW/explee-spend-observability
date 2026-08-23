# PROBLEMS

Open defects in this deliverable. An entry stays OPEN only with a stated reason.

## 2026-08-23 09:35 — README names our hosting vendor

**Status**: OPEN — deferred by minutes, not by scope
**Where**: `README.md`, the "How it runs" section, the line beginning "Contabo VPS"

Our own outbound gate flags it: `Contabo` is one of this machine's ssh host aliases, so
`submission_scan.py` treats it as a private identifier. It is a hosting vendor's brand
rather than a credential, so the exposure is small — but the fix costs nothing and the
rule says redact by substitution.

**Fix**: replace "Contabo VPS" with "a small VPS". Do not delete the section.

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
