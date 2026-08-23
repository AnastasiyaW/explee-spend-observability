# Spend observability across 15 provider accounts

**Dashboard:** https://anastasiyaw.github.io/explee-spend-observability/ (public, no login)
**Collector:** [`spend_monitor.py`](spend_monitor.py) — one file, stdlib only
**Alerts:** [`alerts.jsonl`](alerts.jsonl) — one JSON line per alert

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
| `burn_anomaly` | recent burn ≥ **4×** the 4h median, sustained ≥ **10 min** | the task's own example is "~4x above normal, sustained 20min"; firing at half the sustain gives warning while it is still actionable |
| `runway` | < **24 h** (warn), < **6 h** (critical) | 24h is one working day of notice; 6h is "top up now" |
| `stale` | **3** consecutive failed reads | measured: single failures are injected and rotate, so 1 would be pure noise |
| `world` | epoch or fingerprint changes | every baseline before it is void |
| `shape` | a provider's response layout changes | the fallback parser keeps returning *a* number; the risk is that it now means something else |
| `credits_low` | ≤ 10% of package left | a package cannot be topped up mid-cycle, only waited out |
| `debt` | postpaid balance negative **and** growing | negative is normal for `vastai`; the rate is the signal |
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

## How it runs

```
Contabo VPS ──outbound only──> jobs.explee.com   (poll /meta + 15 balances, 20s, staggered)
     │
     ├─ SQLite: every sample, verbatim body kept as evidence
     ├─ alerts.jsonl
     └─ every 5 min ──> git push ──> branch `data` ──> raw.githubusercontent
                                                              │
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
- **The self-test proves the shapes I thought of.** It covers seven response
  layouts captured verbatim from the live stand and every detector, but a green
  suite is evidence about imagined cases, not a closed class.
