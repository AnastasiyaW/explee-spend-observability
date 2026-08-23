---
name: distill-feedback
description: Turn captured user-correction signals into durable rules (learn-from-corrections loop). Use when - /distill-feedback, "process feedback queue", "what corrections did I give you", "encode lessons from my corrections", session-feedback-capture queued sessions, "обнови правила по моим поправкам", "разбери очередь обратной связи". Reads ~/.claude/feedback/queue.jsonl, LLM-semantically detects durable corrections, proposes atomic rules, applies human-gated via delta-merge. Do NOT use to act on a single in-session correction (just apply the fix directly) or to hand-edit settings.json behaviors; this only mines the queued feedback backlog into durable rules.
---

# distill-feedback — close the learn-from-corrections loop

Submission note: this is a compact submission copy of the skill used at
`~/.claude/skills/distill-feedback/SKILL.md`, with its operating rubric and gates preserved. It
turns queued corrections into deduplicated rule proposals and never writes them without approval.

The Stop hook `session-feedback-capture.py` queues finished sessions into
`~/.claude/feedback/queue.jsonl`. This skill processes that queue: it finds the user turns
that were **durable corrections** of the agent's work and turns them into rules — so the same
correction never has to be given twice.

**Why LLM-semantic, not keywords:** we independently tested a keyword detector. It scored F1
**0.42** on held-out cases and missed ~60% of real corrections (every keyword-free one, e.g.
"в следующий раз лучше через python"). An LLM applying the rubric below scored F1 **0.97** on the
same set. So detection is semantic. Evidence is retained in the private research archive.

**Why human-gated:** a noisy extractor poisons the rule set. Altering durable rules is also above
the auto-act line. So this skill **proposes**; the user approves before anything is written.

## Procedure

### 1. Extract the queue (deterministic)

```bash
python ~/.claude/skills/distill-feedback/scripts/extract_feedback_queue.py --limit 8
```

Returns JSON: `{pending, sessions:[{session_id, cwd, ts, user_turns:[...]}]}`. `--limit` bounds
the LLM pass (billing: distillation is opt-in, not every-session). If `pending` is 0, stop — nothing
to do.

### 2. Detect durable corrections (LLM-semantic, prefer a fresh sub-agent)

For independence (Generator-Evaluator), spawn a sub-agent with the **rubric** below and the
extracted `user_turns`. Ask it to return, per genuine correction: `{quote, durable_rule,
applicability_condition, confidence, session_id}`. Pass only the turns — not your own reasoning.

**RUBRIC — a user turn is a DURABLE CORRECTION** if the user pushes back on or redirects the agent's
behavior in a way that implies a standing preference or a mistake to avoid in future:

- explicit pushback / redirection ("no, do X instead", "wrong file again")
- reminder of a prior agreement ("we agreed you'd ask first", "мы же договаривались сначала бэкап")
- standing-preference marker ("from now on / always / never / by default / в следующий раз / впредь")
- frustration at a repeated mistake ("опять", "again", "you keep")
- polite redirection phrased as a question ("could you not overwrite latest.pth each time?")
- revert with a reason ("верни как было, твоя версия хуже")
- **praise then correction — judge the whole turn** ("great it runs, but always pin versions" = YES)

**NOT a durable correction:** new feature/task request; diagnostic question ("why did the build
fail?", "почему-то падает"); factual statement even with "should be / by default / never";
agreement; reassurance; praise-only; off-topic chatter.

### 3. Deduplicate and draft atomic rules

For each detected correction, write one atomic rule with an applicability condition. Search existing
rules and project memory first: if it already exists, propose an EDIT, not a duplicate ADD. Cluster
duplicates across sessions into one rule.

### 4. Propose (human gate — mandatory)

Show a compact table with each proposed rule, applicability condition, source quote, target file,
and action (`ADD`, `EDIT`, `SUPERSEDE`, or `SPLIT`). Do not write yet. `SUPERSEDE` and `DELETE`
always need explicit confirmation.

### 5. Apply (delta-merge, never rewrite)

On approval, apply each accepted delta with addressable ADD/EDIT only, deduplicate, and preserve
nuance. Put a global rule in the global rules tree and a project-specific lesson in that project's
memory. If a rule is mechanically checkable, nominate it for graduation to a hook or validator;
deterministic enforcement beats recurring prose.

### 6. Mark processed

```bash
python ~/.claude/skills/distill-feedback/scripts/extract_feedback_queue.py --mark-processed <session_id> ...
```

This appends to `processed.jsonl`; the queue is never rewritten. The next session's pending count
drops accordingly.

## Gotchas

- **Transcript may be gone.** If a queued transcript no longer exists, mark the pointer processed;
  do not invent the lost lesson.
- **Do not auto-apply.** Even high-confidence corrections go through the human gate. A wrong rule is
  worse than a missed one because it fires on every future session.
- **Praise-then-correction is the main miss.** "Спасибо, но впредь не трогай прод" is a correction.
- **Billing is bounded.** Distillation runs on demand with `--limit`, never on every session.
- **One-off is not durable.** A correction of one filename is not automatically a standing rule.

## Troubleshooting

- Pending count persists but the queue looks empty: queued transcript pointers may be dead; process
  those records explicitly.
- Extractor reports pending sessions but no readable turns: mark the unreadable records processed.
- To pause capture: create `~/.claude/.skip-feedback-capture` or set
  `CLAUDE_SKIP_FEEDBACK_CAPTURE=1`; the Stop hook then no-ops.
