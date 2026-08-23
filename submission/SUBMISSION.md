# What goes in each field of the form

Everything in this folder is built from the repository by
[`scripts`](../render_trace.py) and a build step, so no artefact here was
assembled by hand. Re-running the build reproduces it byte for byte.

## Task 1 — Spend Observability

| field | what to attach or paste |
|---|---|
| **Alert log** * | `alerts.jsonl` — 104 lines, every one carrying `ts` with an explicit offset, `text` and `provider` |
| **Code** | `task1-code.zip` — the collector (`spend_monitor.py`, one file, stdlib only), the publisher, the mutation gate, the dashboard pages and the README |
| **Dashboard link** | `https://anastasiyaw.github.io/explee-spend-observability/spend.html` |
| **Agent trace** | `TRACE-task1.md` — three sessions in order, verbatim, 3.4 MB |

## Task 2 — Transcriber comparison

| field | what to attach or paste |
|---|---|
| **Report link** | `https://anastasiyaw.github.io/explee-spend-observability/stt.html` |
| **Agent trace** | `TRACE-task2.md` — the two sessions this task ran in, verbatim, 3.0 MB |

## Task 3 — Your best artifact

| field | what to attach |
|---|---|
| **The artifact** | `task3-distill-feedback.md` — the skill, plus the three lines saying where it lives and what it does |

## Notes

Paste the contents of `NOTES.txt`.

---

## Before pressing Submit

- The form has a **hidden honeypot field**. Leave any field you cannot see empty;
  filling every input marks the sender as a bot.
- The dashboard link must open with no login. Checked from a clean fetch:
  HTTP 200, and the page renders live data rather than an error state.
- The alert log is the file as it stood at submission time, taken from the
  collector rather than from an older copy in the repository.

## What a reader can verify without trusting any of this

```
python spend_monitor.py --self-test    # detectors, parsers, suppression, offline, ~3s
python mutation_test.py                # re-introduces each fixed defect; 29 of 29 caught
```

The 6-hour condition is checkable from outside, which the database is not: the
published alert log spans 09:26:48Z to the last line, and the `data` branch
carries one snapshot commit roughly every five minutes across the same window.
