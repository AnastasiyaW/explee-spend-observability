# Spend observability across 15 provider accounts

Everything the brief asks for, and where it is:

| asked for | here |
|---|---|
| the code, a file | [`spend_monitor.py`](spend_monitor.py) — one file, stdlib only |
| `alerts.jsonl` | [`alerts.jsonl`](alerts.jsonl) in this repository, and the collector's live copy on the [`data` branch](https://raw.githubusercontent.com/AnastasiyaW/explee-spend-observability/data/alerts.jsonl), refreshed every five minutes |
| a public dashboard, no login | <https://anastasiyaw.github.io/explee-spend-observability/> |
| `TRACE.md` | [`TRACE-task1.redacted.md`](TRACE-task1.redacted.md) — the real session, verbatim; only our own host names and keys are replaced by substitution, nothing is cut or rewritten. Rendered to read as a page: [trace.html](https://anastasiyaw.github.io/explee-spend-observability/trace.html) |
| run it ≥ 6 hours | one unbroken run over 15 providers — and checkable from outside, which the database is not: the published `alerts.jsonl` spans **09:26:48Z → 16:53:44Z (7.4 h)**, and the `data` branch carries one snapshot commit roughly every five minutes across the same window |

Of the 79 alert lines published so far, 79 carry `ts`, `text` and `provider`, and
every `ts` parses with an explicit offset — checked by parsing the file, not by
reading it.

The stand exposes one number per provider and no history. So the history is the
product: every reading is stored, and burn rate, "normal", and time-to-empty are
derived from readings this collector took itself.

---

## What the stand actually returns

Everything below was measured on 2026-08-23, not read off the catalog. The
catalog is useful but it is not the contract.

| provider | observed body | what it really is |
|---|---|---|
| brightdata, twocaptcha, openai, openrouter | `{"balance":993.58,"currency":"USD"}` | flat prepaid |
| evomi | `{"ok":true,"data":{"wallet":{"amount":325.88,"ccy":"usd"}}}` | nested, renamed field |
| scrapfly, zerobounce, findymail, bounceban, elevenlabs, resend | `{"remaining":38691,"package":50000,"refresh":"2026-09-01"}` | monthly credit package |
| vastai | `{"credit":-151.91,"unit":"usd"}` | postpaid — **negative is normal** |
| meta_ads | `{"spend_usd_30d":10659.83,"spend_usd_24h":355.33}` | no balance, trailing spend |
| anthropic | `{"object":"cost_report","amount_cents":11218,"window":"trailing_24h"}` | trailing cost **in cents** |
| tremendous | `{"gbp":2005.07}` | the currency code *is* the field name |

Three of these are traps:

- **`amount_cents`.** Read as dollars, that account looks 100× richer than it
  is. The parser converts minor units and the self-test asserts `11218 → 112.18`.
- **`{"gbp": 2005.07}`.** No key called balance/amount/credit, so a
  keyword parser finds nothing and the account is *silently never read* — which
  looks exactly like an account that never spends.
- **The catalog's `name` field is a different vendor.** `brightdata` is labelled
  "Oxylabs", `openrouter` is "Groq", `vastai` is "RunPod". Keying the URL on
  `name` returns `404 unknown provider` — measured on 3 of 3 attempts. The
  collector keys on `provider` and never hardcodes the list.

## Two things the task text does not mention

**`GET /api/meta` → `{"world_epoch":1787270400.0,"fingerprint":"b3f76a59761b"}`**

Found by reading the submission page's own JavaScript, which says grading
*replays the deterministic world* and posts `stand_fingerprint` and
`stand_world_epoch` alongside the files. The epoch is 2026-08-21T00:00:00Z and
held stable across 57 hours of observation.

Every sample here is keyed by `(world_epoch, fingerprint)`. If the world resets,
each balance jumps at the same instant and every baseline describes a world that
no longer exists — a monitor that misses this produces a storm of false
top-up-shaped noise and a broken idea of normal. The reset gets its own critical
alert and the baseline restarts.

**The faults are injected and they rotate.** Three sweeps of all fifteen, twenty
seconds apart:

- round 1: `findymail` → `{}` with **HTTP 200**; `tremendous` → 429
- round 2: both fine
- round 3: `findymail` → 429

So `{}`-at-200 and 429 are not properties of a provider, they are random faults
sprayed across the fleet. Consequences for the design: a single failure is a
hiccup and must not alert (the threshold is three consecutive), and per-provider
backoff must be gentle because our own pace did not cause the 429.

The `{}`-at-200 case is the dangerous one and gets its own wording: *"the status
says healthy, so spend here is invisible rather than zero"*. A collector that
records that as "no change" paints the account green forever.

## Why there is no total-spend number

USD, GBP and credits do not add up. Credits have no public price. Two accounts
expose no balance at all. Any single "company spend" figure would be a fiction,
so the dashboard does not print one.

The one quantity that *is* comparable across all fifteen is **runway — hours
until empty at the current burn**. Hours are hours whether the account is
denominated in dollars, pounds or credits. The table is sorted by it, soonest
first, and that ordering is the answer to "what should I look at".

## What raises an alert, and why that threshold

| alert | fires when | why this number |
|---|---|---|
| `burn_anomaly` | a **sustained** burn ≥ **4×** the median of per-bucket rates, held ≥ **10 min** | the task's own example is "~4x above normal, sustained 20min"; firing at half the sustain gives warning while it is still actionable. "Sustained" is not decoration: the balance must fall across ≥ 3 separate intervals, which is what tells a burn apart from one coarse step |
| `spend_spike` | for accounts with no balance: **accrual per hour** ≥ 4× the average the trailing total itself implies | a trailing total is not a rate, and neither is the median of its own derivative — that median is zero most of the time, because the window falls as old spend ages out. See the review section |
| `runway` | < **24 h** (warn), < **6 h** (critical), and **0 or less** (critical, "empty, not slow") | 24h is one working day of notice; 6h is "top up now". Two rates are weighed and the shorter answer wins: the four-hour aggregate, and the rate of a burn happening right now |
| `stale` | **3** consecutive failed reads | measured: single failures are injected and rotate, so 1 would be pure noise |
| `world` | epoch or fingerprint changes | every baseline before it is void, and so is every cooldown |
| `shape` | a provider's response layout changes | the fallback parser keeps returning *a* number; the risk is that it now means something else |
| `credits_low` | ≤ 10% of package left | a package cannot be topped up mid-cycle, only waited out |
| `debt` | postpaid debt growing ≥ **4×** its own normal | negative is normal for `vastai` and so is steady growth. Alerting on any growing debt produced twelve identical lines — 17% of every alert written |
| `catalog:change` | a provider appears or disappears | a provider that vanishes stops being watched, which looks like one that stopped spending |

**What is deliberately *not* an alert:** a balance going **up**. Top-ups and the
monthly credit refresh both raise a balance and the task names both as normal
operations. Increases never enter the burn baseline either — one top-up would
otherwise poison "normal" for hours. The self-test asserts both.

Statistics are robust on purpose: **median and MAD, not mean and σ**. With a few
dozen samples and heavy tails, one spike would redefine normal and then hide
itself.

**Warm-up:** anomaly alerts are suppressed until a provider has ≥ 10 burn
samples. Before that the collector has no idea what normal is, and saying so is
better than guessing. The dashboard shows `warming` in that column.

**Noise control:** one line per problem per 30 minutes unless it escalates in
severity. `alerts.jsonl` is only useful if a human can read it end to end.

Every `ts` is ISO-8601 with an explicit `+00:00` offset.

## What an independent review caught

A fresh-context agent was given the code and the live API and told to refute
these claims rather than confirm them. It found eight defects, six of them in
detectors this README had already described as working. All are fixed; the
self-test now kills a mutant for each one.

The three worth naming, because the lesson generalises:

**A median of drops is not a rate.** Burn was computed as the median of
per-interval decreases, which answers "how big is a drop" and not "how fast is
money leaving". An account whose balance moves in coarse steps sits flat between
drops, so dropping the flat intervals inflated the rate by the reciprocal of its
duty cycle — measured at **3.05× on twocaptcha and 2.63× on findymail**. Runway
is balance ÷ rate, so the dashboard published **46.9 h where 143.1 h was true**,
for the accounts it ranked 4th and 5th most urgent. It was a plausible-looking
number, which is why nothing else would ever have flagged it. Now: total drop
divided by total *elapsed* time, bucketed, median across buckets.

**Two detectors could never fire.** The shape-change alert queried the samples
table *after* inserting the current row, so it always found the shape it had
just written and no change was ever visible. The spend-report detector compared
a trailing-24h total against the median of its own 4h of readings — arithmetic
that is bounded near 1.09× and can never reach a threshold of 4.0; over fifteen
live rounds the highest ratio either account reached was 1.0022. Both providers
that expose no balance were unmonitored while this file said otherwise. Now the
shape history is read before the insert, and a trailing total is differentiated
into an accrual rate before anything is compared.

**Resolving an alert deleted its cooldown.** `clear()` removed the state row, so
a value oscillating across a threshold re-fired at full volume: twelve polls
produced six identical lines inside one second. Now a resolved alert keeps its
timestamp.

Also fixed: runway had no warm-up and would publish "1.1 h left, top up now" off
two readings twenty seconds apart; the world key filtered on epoch but not
fingerprint, so a fingerprint-only reset spliced two worlds into one series and
invented a 47,943/h phantom burn; the snapshot was rewritten every second
(~26 GB of writes a day) outside the try that guards polling, so one bad byte in
`alerts.jsonl` would have killed the run permanently.

The previous self-test passed on three of five deliberately broken versions.
The current one kills **twenty-two of twenty-two**, in about a minute; the
self-test itself runs in three seconds.

### A second review, against this brief

The whole thing was then read once more with the published brief open beside it,
which found one gap and two defects the green suite could not see.

**The gap: a required deliverable had no way off the box.** The brief asks for
`alerts.jsonl`. It existed — 69 lines of it — but [`publish.sh`](publish.sh)
copied only `data.json` to the `data` branch, so both links to it returned 404.
An artefact nobody can fetch has not been delivered. Both the repository copy
and the live branch copy now exist, and the publishing script is in the
repository instead of living only on the host.

**A baseline of zero is not the absence of a baseline.** `baseline_rate` returns
the bucket count precisely so a caller can tell those apart, and both call sites
tested the median for truthiness and threw the distinction away. The median is
exactly `0.0` for an account that steps less often than a bucket is wide — and
the fallback was the 15-minute burn, which is the duty-cycle error a third time
and the worst instance of it yet: on a four-hourly stepper it reads 450/h
against a true 12.5/h and publishes *"2.1h of runway left, top up now"* for an
account 76 hours from empty. None of the fifteen live accounts steps that slowly
today, so this had not fired — it was one quiet provider away. A zero median now
falls back to the aggregate over the whole baseline window, which is still a
rate and still counts the flat time.

**A sustain clock that never resets.** `_balance` clears its anomaly timer when
the burst ends; `_spend_report` did not. After one blip, the "sustained ≥ 10 min"
requirement was permanently satisfied for `anthropic` and `meta_ads`: the next
single sample would fire instantly and quote a duration measured from an
unrelated event hours earlier.

**The dashboard executed whatever the stand sent it.** Provider names, error
text, fault kinds and the world fingerprint went into `innerHTML` unescaped, so
`{"error":"<img src=x onerror=...>"}` would have run as script on the Pages
origin. Every page escapes now. The check that proves it is not "I read the
code": each page's own `render()` was run over a hostile payload and the HTML it
produced was inspected — 14 sinks, and the first run of that probe found a
fifteenth I had missed by eye.

### A third pass, adversarial, and what it cost me

A fresh agent was then given the code and told to refute the two fixes above
rather than confirm them. It refuted one of mine and found six more, all with
reproductions. Every one is fixed and carries both a regression and a mutant.

**My own fix traded a false alarm for silence.** Sending runway to the four-hour
aggregate removed the bogus critical — and then an account burning 4,000/h for
the last fifteen minutes published *35.8 hours* of runway and said nothing,
because fifteen minutes barely moves a four-hour average. That is the worse
mistake of the two. Both rates are now weighed and the shorter answer wins,
which needs a way to tell a burn from one coarse step: a burn moves the balance
across several intervals in a row.

**The spend detector could not fire in the regime the stand actually produces.**
Its baseline was the median of its own derivative, and a trailing window falls
as old spend ages out — measured over our own seven hours, anthropic's
trailing-24h figure fell on **768 of 1,148** readings and meta_ads' on 541 of
1,161. Most buckets are therefore zero, the median is zero, and the detector
returned before comparing anything. The baseline is now the average the level
itself implies.

**A balance of exactly 0.00 raised nothing** while 0.01 raised a critical: the
guard was `value > 0`. The one account that is actually empty was the one that
got silence.

**Steady postpaid debt alerted forever** — no threshold at all, twelve identical
`vastai` lines, 17% of every alert in the file. It now needs acceleration.

Also fixed: an outage left the sustain clock running, so the first sample after
half an hour of failures fired instantly claiming to have watched a burst
through the outage; a new world inherited the old world's cooldown, swallowing
its first alert; and `healthy` had no age bound, so a stopped collector painted
the whole board green.

One thing worth saying plainly: the suite was green before this pass, and green
again after it. That is the point of the mutation gate — it asks whether the
tests can fail, not whether they pass.

## About the trace

The work ran across two harnesses, so the trace is in two parts and both are
here: the Claude Code session that built the collector, and the Codex session
that carried it on. They are exported by the same rules and rendered on one
page, in order.

**What is removed, and nothing else:** duplicate records for a message that was
typed mid-turn, `<system-reminder>` blocks that hooks inject into a user turn,
editor bookkeeping with no conversational content, and tool output past a stated
cap — where every cut says how many characters went. The exporter's own header
records the bug that made those rules necessary: an earlier version counted 91
"user" messages when the human had written eight, because tool results arrive
under the same role and mid-turn messages arrive as a different record type
entirely, which was on the skip list.

**What is replaced, never deleted:** our own host names, keys, client names and
private paths, each by a stable placeholder. Deleting a message to hide
something would forge the trace; substituting a hostname does not. The mapping
stays on this machine. One thing that pass missed the first time and this one
caught: the map was built from Latin spellings, so the hosting vendor's name
went out **eight times in Cyrillic**, inside Russian sentences, in a file whose
header said it was redacted. Both alphabets are in the gate now.

**Typos are not corrected in the record.** The brief is explicit that a
hand-made trace tells them nothing, and fast unedited typing is part of what it
shows. The page therefore opens on the verbatim text and offers a
spelling-corrected reading as a switch, built from
[`trace-corrections.json`](trace-corrections.json) — explicit find/replace pairs,
so which characters changed is auditable rather than buried in a rewritten file.
Each pair must match its message exactly once or the render fails. One of them
is interpretation rather than spelling, and that one is named in the file.

## How it runs

```
a small VPS ──outbound only──> jobs.explee.com   (poll /meta + 15 balances, 20s, staggered)
     │
     ├─ SQLite: every sample, verbatim body kept as evidence
     ├─ alerts.jsonl
     └─ every 5 min ──> publish.sh ──> branch `data` ──> raw.githubusercontent
            (data.json AND alerts.jsonl)                      │
                            GitHub Pages (docs/) ─────────────┘  dashboard fetches it
```

**Nothing listens.** The collector opens no port; the box has no inbound path
for this service at all, so there is nothing to reach. It runs as a hardened
`systemd --user` unit (`NoNewPrivileges`, `ProtectSystem=strict`, `PrivateTmp`,
write access limited to its own directory) and publishes with a deploy key
scoped to this one public repository.

```bash
python3 spend_monitor.py --self-test   # detectors, parsers and suppression, offline
python3 spend_monitor.py once          # one sweep of all 15 against the live stand
python3 spend_monitor.py run           # the monitor
```

## Limits, stated plainly

- **Credits cannot be priced.** Runway for a credit package is in credits/hour,
  not money. Converting would need a price the stand does not publish.
- **GBP is not converted to USD.** No rate source, and inventing one would make
  the headline number wrong in a way nobody could see.
- **Spend-report accounts have no runway.** `anthropic` and `meta_ads` expose
  only trailing cost, so they get anomaly detection on that series and nothing
  else. That is the ceiling of what those endpoints allow.
- **`raw.githubusercontent` caches for a few minutes.** The dashboard polls
  every 30s, but the underlying data is at most ~5 minutes old. For runway
  measured in hours that is well inside the noise.
- **A single coarse step is never treated as an anomaly.** A burn has to move
  the balance across at least three intervals before either detector looks at
  it, so an account that spends in one large step every few hours is judged on
  its four-hour rate alone. That is deliberate: the alternative fires once per
  step, forever.
- **Nothing is deleted, so the database grows.** Every sample keeps the first
  600 bytes of the body as evidence, which is roughly 50 MB a day at this poll
  rate. Correct for a run measured in hours, wrong for a service left running;
  retention is a decision about discarding evidence and has not been taken.
- **The self-test proves the shapes I thought of.** It covers seven response
  layouts captured verbatim from the live stand and every detector, but a green
  suite is evidence about imagined cases, not a closed class. That is not a
  figure of speech: the suite was green when the review above started.
