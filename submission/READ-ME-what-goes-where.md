# What goes in each field of the form

Every file here is named after the field it belongs in, and the two links are in
`LINKS-to-paste.txt` so nothing has to be typed. Nothing in this folder was
assembled by hand: it is built from the repository by a script, and re-running
that script reproduces it byte for byte.

## Task 1 — Spend Observability

| field | file or link |
|---|---|
| **Alert log** * | `Task1-1-alerts.jsonl` — 104 lines; every one carries `ts` with an explicit offset, `text` and `provider` |
| **Code** | `Task1-2-code.zip` — the collector (one file, stdlib only), the publisher, the mutation gate, the dashboard pages, the README |
| **Dashboard link** | `https://anastasiyaw.github.io/explee-spend-observability/spend.html` |
| **Agent trace** | `Task1-4-TRACE.md` — three sessions in order, verbatim, 3.4 MB |

## Task 2 — Transcriber comparison

| field | file or link |
|---|---|
| **Report link** | `https://anastasiyaw.github.io/explee-spend-observability/stt.html` |
| **Agent trace** | `Task2-2-TRACE.md` — the two sessions this task ran in, verbatim, 3.0 MB |

## Task 3 — Your best artifact

| field | file |
|---|---|
| **The artifact** | `Task3-artifact.md` — the skill, plus the three lines saying where it lives and what it does |

## Notes

Paste the contents of `Notes-paste-into-form.txt`.

---

## Before pressing Submit

- The form carries a **hidden honeypot field**. Fill in only the fields you can
  see; filling every input marks the sender as a bot.
- The dashboard link must open with no login. Checked from a clean fetch: HTTP
  200, and the page renders live data rather than an error state.
- The alert log is the file as it stood at submission time, taken from the
  collector rather than from an older copy in the repository.

## What a reader can check without trusting any of this

```
python spend_monitor.py --self-test    # detectors, parsers, suppression, offline, ~3 s
python mutation_test.py                # re-introduces each fixed defect; 29 of 29 caught
```

The six-hour condition is verifiable from outside, which the database is not:
the published alert log spans 09:26:48Z to 19:46:19Z — 10.3 hours — and the
`data` branch carries one snapshot commit roughly every five minutes across the
same window.
