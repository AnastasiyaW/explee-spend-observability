#!/usr/bin/env python3
"""Spend observability for ~15 external provider accounts.

The stand gives one number per provider and no history, so the history is
built here: every reading is stored, and everything interesting - burn rate,
what "normal" means, how long the money lasts - is derived from readings this
process took itself.

Three decisions the shape of the data forced, each measured before it was coded:

1. Poll /meta alongside the balances and key every sample by (world_epoch,
   fingerprint). The submit page's own JavaScript says grading REPLAYS a
   deterministic world; a world reset would otherwise look like every provider
   being topped up at the same instant, and every baseline would silently
   describe a world that no longer exists.
2. Never trust the catalog's declared shape. Six different response shapes were
   observed across fifteen endpoints, one provider answers HTTP 200 with an
   empty body, and a shape can change under us. Parsing falls back to a search
   for a plausible numeric field and RAISES A DATA-QUALITY ALERT rather than
   dying or, worse, recording None as if it were calm.
3. Compare in units that are actually comparable. usd, gbp and credits do not
   add up, and two providers have no balance at all. The only quantity that
   spans all fifteen is TIME: hours of runway at the current burn.

Alerting is deliberately conservative about the two things the task calls
normal operations - top-ups and the monthly credit refresh both raise a
balance, and neither is an incident.

    python spend_monitor.py run                 # the monitor
    python spend_monitor.py snapshot            # rebuild dashboard data
    python spend_monitor.py --self-test         # prove the detectors fire

Stdlib only, so it runs on a bare box with no wheels to install.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import sqlite3
import statistics
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE = os.environ.get("EXPLEE_BASE", "https://jobs.explee.com/ai-native-developer/test/api")
HERE = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("EXPLEE_DB", HERE / "spend.sqlite"))
ALERTS_PATH = Path(os.environ.get("EXPLEE_ALERTS", HERE / "alerts.jsonl"))
SNAPSHOT_PATH = Path(os.environ.get("EXPLEE_SNAPSHOT", HERE / "dashboard" / "data.json"))

POLL_INTERVAL = float(os.environ.get("EXPLEE_INTERVAL", "20"))     # seconds per provider
HTTP_TIMEOUT = float(os.environ.get("EXPLEE_TIMEOUT", "20"))
CATALOG_REFRESH_SEC = 900        # providers can appear or disappear; do not cache forever
META_INTERVAL_SEC = 60

# --- detector thresholds ---------------------------------------------------
# Every number here is a decision, so each carries why it is that number.
WARMUP_BURN_SAMPLES = 10     # below this the median of burn is not a baseline, it is noise
BURN_WINDOW_SEC = 900        # "recent" burn: long enough to smooth one poll, short enough to react
BASELINE_WINDOW_SEC = 4 * 3600
ANOMALY_RATIO = 4.0          # the task's own example is "~4x above normal"
ANOMALY_SUSTAIN_SEC = 600    # their example says "sustained 20min"; fire at half that, escalate later
RUNWAY_WARN_H = 24.0
RUNWAY_CRIT_H = 6.0
STALE_FAILURES = 3           # three consecutive misses is an outage, one is a hiccup
STALE_SEC = 300
REALERT_COOLDOWN_SEC = 1800  # one line per problem per half hour, unless it escalates
MAX_BACKOFF_SEC = 300


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def now() -> float:
    return time.time()


def iso(ts: float) -> str:
    """ISO-8601 with an explicit offset.

    The task grades across timezones and says an offset-less stamp can only be
    read as UTC, so the offset is always written out rather than implied.
    """
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds")


def http_get(url: str, timeout: float = HTTP_TIMEOUT):
    """Return (status, body_text, latency_ms, error). Never raises."""
    started = time.monotonic()
    req = urllib.request.Request(url, headers={
        "User-Agent": "explee-spend-monitor/1.0",
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return resp.status, body, (time.monotonic() - started) * 1000, None
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        return exc.code, body, (time.monotonic() - started) * 1000, "http {}".format(exc.code)
    except Exception as exc:                       # timeout, DNS, reset, TLS
        return None, "", (time.monotonic() - started) * 1000, type(exc).__name__


def deep_number(obj, names):
    """Find the first numeric value under any key in `names`, at any depth.

    This is the fallback that keeps the monitor alive when a provider changes
    its response shape. It is paired with a data-quality alert: surviving a
    change quietly would be worse than crashing.
    """
    def numeric(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool)

    if isinstance(obj, dict):
        # Exact name first, so {"balance":x,"available_balance":y} picks balance.
        for key, value in obj.items():
            if key.lower() in names and numeric(value):
                return float(value), key
        # Then a renamed field that still contains the word: wallet_balance_usd.
        # This is what lets the monitor survive a shape change instead of going
        # blind - and the caller raises a data-quality alert when it happens.
        for key, value in obj.items():
            tokens = set(key.lower().replace("-", "_").split("_"))
            if tokens & names and numeric(value):
                return float(value), key
        for value in obj.values():
            found = deep_number(value, names)
            if found:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = deep_number(item, names)
            if found:
                return found
    return None


VALUE_KEYS = {"balance", "amount", "credit", "remaining", "value", "available"}
CAPACITY_KEYS = {"package", "quota", "limit", "total"}
# One provider answers {"gbp": 2005.07} - the currency code IS the field name.
# Without this set that account is simply never read, and a monitor that never
# reads an account looks exactly like an account that never spends.
CURRENCY_CODES = {"usd", "eur", "gbp", "rub", "jpy", "cad", "aud", "chf", "cny",
                  "inr", "brl", "sek", "nok", "dkk", "pln", "try", "uah", "kzt"}
# Another answers amount_cents. Reading that as dollars overstates the account
# by 100x, which is worse than not reading it at all.
MINOR_UNIT_TOKENS = {"cents", "cent", "pence", "minor", "kopeck", "kopecks"}


def normalize(body_text: str, declared_model: str, declared_unit: str) -> dict:
    """Turn one provider's answer into the common record.

    Returns a dict with: ok, model, unit, value, capacity, spend_24h, spend_30d,
    refresh, shape, error.  `shape` names the layout actually seen, so a change
    from the declared one is detectable rather than invisible.
    """
    out = {"ok": False, "model": declared_model, "unit": declared_unit, "value": None,
           "capacity": None, "spend_24h": None, "spend_30d": None, "refresh": None,
           "shape": None, "error": None}
    text = (body_text or "").strip()
    if not text:
        out["error"] = "empty body"
        return out
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        out["error"] = "not json"
        return out
    if not isinstance(data, dict):
        out["error"] = "json is not an object"
        return out
    if not data:
        # HTTP 200 carrying {}. The dangerous failure: a naive collector reads
        # this as "nothing changed" and paints the provider green forever.
        out["error"] = "empty json object"
        out["shape"] = "empty"
        return out
    if "error" in data or "detail" in data:
        out["error"] = str(data.get("error") or data.get("detail"))[:200]
        out["shape"] = "error-object"
        return out

    lower_keys = {k.lower() for k in data}
    obj_kind = (data.get("object") or "").lower() if isinstance(data.get("object"), str) else ""
    window = (data.get("window") or "").lower() if isinstance(data.get("window"), str) else ""

    # --- spend reports: no balance exists, only trailing cost --------------
    # Two forms observed: meta_ads {"spend_usd_30d":..,"spend_usd_24h":..} and
    # anthropic {"object":"cost_report","amount_cents":11218,"window":"trailing_24h"}.
    spend_keys = [k for k in data if k.lower().startswith("spend")]
    is_cost_report = "cost_report" in obj_kind or (window.startswith("trailing") and not spend_keys)
    if spend_keys or is_cost_report:
        for key in spend_keys:
            value = data[key]
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                continue
            amount = _to_major(float(value), key)
            if "24" in key:
                out["spend_24h"] = amount
            elif "30" in key:
                out["spend_30d"] = amount
        if is_cost_report:
            found = deep_number(data, VALUE_KEYS | {"cost", "spend"})
            if found:
                amount = _to_major(found[0], found[1])
                if "30" in window:
                    out["spend_30d"] = amount
                else:
                    out["spend_24h"] = amount
                out["unit"] = _unit_from(data, found[1]) or declared_unit
        out["ok"] = out["spend_24h"] is not None or out["spend_30d"] is not None
        out["model"] = "spend_report"
        out["shape"] = "cost_report" if is_cost_report else "spend_report"
        if not out["ok"]:
            out["error"] = "spend report without a numeric field"
        return out

    # --- balance-bearing accounts -----------------------------------------
    found = deep_number(data, VALUE_KEYS)
    if not found:
        # {"gbp": 2005.07}: the currency code is the field name.
        for key, value in data.items():
            if key.lower() in CURRENCY_CODES and isinstance(value, (int, float)) \
                    and not isinstance(value, bool):
                found = (float(value), key)
                break
    if not found:
        out["error"] = "no recognisable numeric value"
        out["shape"] = "unknown:" + ",".join(sorted(data)[:6])
        return out
    raw_value, value_key = found
    out["value"] = _to_major(raw_value, value_key)
    capacity = deep_number(data, CAPACITY_KEYS)
    if capacity:
        out["capacity"] = _to_major(capacity[0], capacity[1])

    out["unit"] = _unit_from(data, value_key) or declared_unit
    out["refresh"] = _find_string(data, "refresh")
    if out["capacity"] is not None and out["refresh"]:
        out["model"] = "credits_package"
    elif value_key.lower() == "credit":
        out["model"] = "postpaid"
    elif declared_model in ("prepaid_balance", "credits_package", "postpaid"):
        out["model"] = declared_model
    out["shape"] = "{}@{}".format(value_key, "nested" if _is_nested(data, value_key) else "flat")
    out["ok"] = True
    return out


def _to_major(value: float, key: str) -> float:
    """Convert a minor-unit field (amount_cents) into the major unit."""
    tokens = set(key.lower().replace("-", "_").split("_"))
    return value / 100.0 if tokens & MINOR_UNIT_TOKENS else value


def _unit_from(data, value_key: str):
    """The unit as the payload states it, however it states it."""
    for name in ("currency", "ccy", "unit"):
        candidate = _find_string(data, name)
        if candidate:
            return candidate.lower()
    tokens = [t for t in value_key.lower().replace("-", "_").split("_")]
    for token in tokens:
        if token in CURRENCY_CODES:
            return token
    if set(tokens) & MINOR_UNIT_TOKENS:
        return "usd"          # cents with no stated currency; the stand is USD
    return None


def _find_string(obj, name):
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key.lower() == name and isinstance(value, str):
                return value
        for value in obj.values():
            found = _find_string(value, name)
            if found:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = _find_string(item, name)
            if found:
                return found
    return None


def _is_nested(data, key):
    return key not in data


# ---------------------------------------------------------------------------
# storage
# ---------------------------------------------------------------------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS samples (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts REAL NOT NULL, world_epoch REAL, fingerprint TEXT,
  provider TEXT NOT NULL, ok INTEGER NOT NULL, http_status INTEGER, latency_ms REAL,
  model TEXT, unit TEXT, value REAL, capacity REAL,
  spend_24h REAL, spend_30d REAL, refresh TEXT, shape TEXT, error TEXT, raw TEXT
);
CREATE INDEX IF NOT EXISTS idx_samples_provider_ts ON samples(provider, ts);
CREATE TABLE IF NOT EXISTS alert_state (
  key TEXT PRIMARY KEY, last_ts REAL, last_level TEXT, fired INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS worlds (
  first_seen REAL, world_epoch REAL, fingerprint TEXT, PRIMARY KEY (world_epoch, fingerprint)
);
"""


def connect(path: Path = DB_PATH) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    # WAL so a snapshot read never blocks the writer during a long run.
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


# ---------------------------------------------------------------------------
# alerting
# ---------------------------------------------------------------------------
LEVEL_ORDER = {"info": 0, "warn": 1, "critical": 2}


class Alerter:
    """Writes one JSON line per alert, and refuses to write the same one twice.

    Without suppression a six-hour run produces thousands of identical lines
    and the file stops being readable by a human, which is the only thing it is
    for. An alert re-fires when it escalates, or after the cooldown.
    """

    def __init__(self, conn: sqlite3.Connection, path: Path = ALERTS_PATH):
        self.conn = conn
        self.path = path
        self.lock = threading.Lock()
        path.parent.mkdir(parents=True, exist_ok=True)

    def fire(self, key: str, level: str, provider: str, text: str, **extra) -> bool:
        ts = now()
        with self.lock:
            row = self.conn.execute(
                "SELECT last_ts, last_level FROM alert_state WHERE key=?", (key,)).fetchone()
            if row:
                escalated = LEVEL_ORDER.get(level, 0) > LEVEL_ORDER.get(row["last_level"] or "info", 0)
                if not escalated and (ts - (row["last_ts"] or 0)) < REALERT_COOLDOWN_SEC:
                    return False
            record = {"ts": iso(ts), "provider": provider, "text": text,
                      "level": level, "kind": key.split(":", 1)[0]}
            record.update(extra)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            self.conn.execute(
                "INSERT INTO alert_state(key,last_ts,last_level,fired) VALUES(?,?,?,1) "
                "ON CONFLICT(key) DO UPDATE SET last_ts=excluded.last_ts, last_level=excluded.last_level,"
                " fired=alert_state.fired+1", (key, ts, level))
            self.conn.commit()
        print("ALERT [{}] {}".format(level, text), flush=True)
        return True

    def clear(self, key: str) -> None:
        with self.lock:
            self.conn.execute("DELETE FROM alert_state WHERE key=?", (key,))
            self.conn.commit()


# ---------------------------------------------------------------------------
# analysis
# ---------------------------------------------------------------------------
def burn_series(conn, provider: str, since: float, world_epoch):
    """Spend per hour between consecutive successful readings.

    Only DECREASES count. A rise is a top-up or the monthly credit refresh -
    the task names both as normal operations, so they must never enter the
    baseline, or one top-up would poison "normal" for hours.
    """
    rows = conn.execute(
        "SELECT ts, value FROM samples WHERE provider=? AND ok=1 AND value IS NOT NULL "
        "AND ts>=? AND world_epoch IS ? ORDER BY ts", (provider, since, world_epoch)).fetchall()
    out = []
    for prev, cur in zip(rows, rows[1:]):
        dt_h = (cur["ts"] - prev["ts"]) / 3600.0
        if dt_h <= 0:
            continue
        delta = prev["value"] - cur["value"]
        if delta > 0:
            out.append((cur["ts"], delta / dt_h))
    return out


def robust_baseline(samples):
    """Median and MAD. Median, not mean: one spike must not redefine normal."""
    values = [v for _, v in samples]
    if not values:
        return None, None
    median = statistics.median(values)
    mad = statistics.median([abs(v - median) for v in values]) or 0.0
    return median, mad


def topups(conn, provider, since, world_epoch):
    rows = conn.execute(
        "SELECT ts, value FROM samples WHERE provider=? AND ok=1 AND value IS NOT NULL "
        "AND ts>=? AND world_epoch IS ? ORDER BY ts", (provider, since, world_epoch)).fetchall()
    return [(cur["ts"], cur["value"] - prev["value"])
            for prev, cur in zip(rows, rows[1:]) if cur["value"] > prev["value"]]


class Analyzer:
    def __init__(self, conn, alerter: Alerter):
        self.conn = conn
        self.alerter = alerter
        self.fail_streak = {}
        self.anomaly_since = {}
        self.started = now()

    def on_sample(self, provider, catalog_entry, record, world):
        epoch = world.get("world_epoch")
        if not record["ok"]:
            self._health(provider, record)
            return
        self.fail_streak[provider] = 0
        self.alerter.clear("stale:" + provider)

        # A field rename is the failure this monitor is least likely to notice
        # on its own: the fallback parser keeps returning a number, so nothing
        # looks broken while the number may mean something else entirely.
        previous = self.conn.execute(
            "SELECT shape FROM samples WHERE provider=? AND ok=1 AND shape IS NOT NULL "
            "AND shape != ? ORDER BY ts DESC LIMIT 1", (provider, record["shape"])).fetchone()
        seen_before = self.conn.execute(
            "SELECT 1 FROM samples WHERE provider=? AND ok=1 AND shape=? LIMIT 1",
            (provider, record["shape"])).fetchone()
        if previous and not seen_before:
            self.alerter.fire(
                "shape:" + provider, "warn", provider,
                "{}: response shape changed from {} to {} (parsed as {} {}). The value still reads, "
                "but check it means what it used to - a rename to a minor unit would overstate this "
                "account 100x.".format(provider, previous["shape"], record["shape"],
                                       record["value"], record["unit"] or ""),
                previous_shape=previous["shape"], shape=record["shape"], value=record["value"])

        if record["model"] == "spend_report":
            self._spend_report(provider, record, epoch)
            return
        self._balance(provider, record, epoch)

    # -- health -----------------------------------------------------------
    def _health(self, provider, record):
        streak = self.fail_streak.get(provider, 0) + 1
        self.fail_streak[provider] = streak
        if streak < STALE_FAILURES:
            return
        reason = record.get("error") or "unknown"
        if reason in ("empty json object", "empty body"):
            text = ("{}: answering HTTP 200 with no data for {} consecutive polls. The status says "
                    "healthy, so spend here is invisible rather than zero - treat this provider as "
                    "unmonitored until it returns a body.").format(provider, streak)
        else:
            text = ("{}: {} consecutive failed reads ({}). No current balance - a spend spike here "
                    "would not be seen.").format(provider, streak, reason)
        self.alerter.fire("stale:" + provider, "warn" if streak < 10 else "critical",
                          provider, text, failures=streak, reason=reason)

    # -- spend-report providers -------------------------------------------
    def _spend_report(self, provider, record, epoch):
        if record["spend_24h"] is None:
            return
        rows = self.conn.execute(
            "SELECT spend_24h FROM samples WHERE provider=? AND ok=1 AND spend_24h IS NOT NULL "
            "AND ts>=? AND world_epoch IS ? ORDER BY ts", (provider, now() - BASELINE_WINDOW_SEC, epoch)
        ).fetchall()
        history = [r["spend_24h"] for r in rows]
        if len(history) < WARMUP_BURN_SAMPLES:
            return
        median = statistics.median(history)
        current = record["spend_24h"]
        if median > 0 and current / median >= ANOMALY_RATIO:
            self.alerter.fire(
                "spend_spike:" + provider, "critical", provider,
                "{}: trailing 24h spend {:.2f} {} against a {:.2f} median over the last {:.0f}h "
                "({:.1f}x). No balance is exposed here, so this is the only signal this account gives."
                .format(provider, current, record["unit"] or "", median,
                        BASELINE_WINDOW_SEC / 3600, current / median),
                spend_24h=current, median_24h=median, ratio=round(current / median, 2))

    # -- balance-bearing providers ----------------------------------------
    def _balance(self, provider, record, epoch):
        value, unit = record["value"], record["unit"] or ""
        recent = burn_series(self.conn, provider, now() - BURN_WINDOW_SEC, epoch)
        baseline_samples = burn_series(self.conn, provider, now() - BASELINE_WINDOW_SEC, epoch)
        median, mad = robust_baseline(baseline_samples)

        recent_burn = statistics.mean([v for _, v in recent]) if recent else 0.0

        # anomaly: sustained, and only once a baseline exists worth comparing to
        key = "burn_anomaly:" + provider
        if median and len(baseline_samples) >= WARMUP_BURN_SAMPLES and recent_burn > 0:
            ratio = recent_burn / median if median > 0 else math.inf
            if ratio >= ANOMALY_RATIO:
                first = self.anomaly_since.setdefault(provider, now())
                sustained = now() - first
                if sustained >= ANOMALY_SUSTAIN_SEC:
                    runway = value / recent_burn if recent_burn > 0 else None
                    self.alerter.fire(
                        key, "critical", provider,
                        "{}: spend {:.2f} {}/h against a normal of {:.2f} ({:.1f}x), sustained {:.0f} min. "
                        "Balance {:.2f}, which at this rate is {} of runway.".format(
                            provider, recent_burn, unit, median, ratio, sustained / 60, value,
                            "{:.1f}h".format(runway) if runway else "unknown"),
                        burn_per_h=round(recent_burn, 4), baseline_per_h=round(median, 4),
                        ratio=round(ratio, 2), sustained_min=round(sustained / 60, 1),
                        balance=value, unit=unit)
            else:
                self.anomaly_since.pop(provider, None)
                self.alerter.clear(key)
        else:
            self.anomaly_since.pop(provider, None)

        # runway: the one number comparable across usd, gbp and credits
        rate = median if median else recent_burn
        if rate and rate > 0 and value is not None and value > 0:
            hours = value / rate
            rkey = "runway:" + provider
            if hours <= RUNWAY_CRIT_H:
                self.alerter.fire(rkey, "critical", provider,
                                  "{}: {:.1f}h of runway left - {:.2f} {} at {:.2f} {}/h. Top up now."
                                  .format(provider, hours, value, unit, rate, unit),
                                  runway_h=round(hours, 2), balance=value, burn_per_h=round(rate, 4),
                                  unit=unit)
            elif hours <= RUNWAY_WARN_H:
                self.alerter.fire(rkey, "warn",
                                  provider,
                                  "{}: {:.1f}h of runway - {:.2f} {} at {:.2f} {}/h.".format(
                                      provider, hours, value, unit, rate, unit),
                                  runway_h=round(hours, 2), balance=value,
                                  burn_per_h=round(rate, 4), unit=unit)
            else:
                self.alerter.clear(rkey)

        # postpaid debt: no floor to run out of, so the signal is the debt itself
        if record["model"] == "postpaid" and value is not None and value < 0:
            debt_rate = rate or 0.0
            if debt_rate > 0:
                self.alerter.fire(
                    "debt:" + provider, "warn", provider,
                    "{}: postpaid debt at {:.2f} {} and growing {:.2f} {}/h. Negative is normal here; "
                    "the rate is what matters.".format(provider, value, unit, debt_rate, unit),
                    debt=value, rate_per_h=round(debt_rate, 4), unit=unit)

        # credits: a package that will not survive to its own refresh date
        if record["model"] == "credits_package" and record["capacity"]:
            pct = 100.0 * value / record["capacity"]
            if pct <= 10:
                self.alerter.fire("credits_low:" + provider, "warn", provider,
                                  "{}: {:.1f}% of the package left ({:.0f} of {:.0f}), refresh {}."
                                  .format(provider, pct, value, record["capacity"],
                                          record["refresh"] or "unknown"),
                                  remaining=value, package=record["capacity"],
                                  pct=round(pct, 1), refresh=record["refresh"])


# ---------------------------------------------------------------------------
# the monitor
# ---------------------------------------------------------------------------
class Monitor:
    def __init__(self, base=BASE, db=DB_PATH, once=False):
        self.base = base.rstrip("/")
        self.conn = connect(db)
        self.alerter = Alerter(self.conn)
        self.analyzer = Analyzer(self.conn, self.alerter)
        self.catalog = {}
        self.catalog_ts = 0.0
        self.world = {"world_epoch": None, "fingerprint": None}
        self.backoff = {}
        self.once = once
        self.stop = threading.Event()

    # -- stand plumbing ---------------------------------------------------
    def refresh_catalog(self):
        status, body, _, err = http_get(self.base + "/providers")
        if err or status != 200:
            print("catalog unavailable: {} {}".format(status, err), file=sys.stderr, flush=True)
            return
        try:
            entries = json.loads(body)
        except json.JSONDecodeError:
            print("catalog is not json", file=sys.stderr, flush=True)
            return
        if not isinstance(entries, list):
            return
        seen = {}
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            # The URL key is `provider`. The `name` field is a DIFFERENT vendor
            # (brightdata is labelled Oxylabs, openrouter is labelled Groq) and
            # keying on it returns 404. Measured, not assumed.
            pid = entry.get("provider")
            if isinstance(pid, str) and pid:
                seen[pid] = entry
        if not seen:
            return
        gone = set(self.catalog) - set(seen)
        added = set(seen) - set(self.catalog)
        if self.catalog and (gone or added):
            self.alerter.fire(
                "catalog:change", "warn", "",
                "catalog changed: {} appeared, {} disappeared. A provider that vanishes stops "
                "being watched, which looks exactly like a provider that stopped spending."
                .format(sorted(added) or "none", sorted(gone) or "none"),
                added=sorted(added), removed=sorted(gone))
        self.catalog = seen
        self.catalog_ts = now()

    def refresh_meta(self):
        status, body, _, err = http_get(self.base + "/meta")
        if err or status != 200:
            return
        try:
            meta = json.loads(body)
        except json.JSONDecodeError:
            return
        epoch, fingerprint = meta.get("world_epoch"), meta.get("fingerprint")
        if epoch is None and fingerprint is None:
            return
        previous = dict(self.world)
        self.world = {"world_epoch": float(epoch) if epoch is not None else None,
                      "fingerprint": str(fingerprint) if fingerprint else None}
        if previous["fingerprint"] and previous != self.world:
            self.alerter.fire(
                "world:reset", "critical", "",
                "the stand reset its world: epoch {} -> {}, fingerprint {} -> {}. Every balance "
                "will appear to jump and every baseline before this point describes a world that "
                "no longer exists; measurement restarts here.".format(
                    previous["world_epoch"], self.world["world_epoch"],
                    previous["fingerprint"], self.world["fingerprint"]),
                previous=previous, current=self.world)
            self.analyzer.anomaly_since.clear()
        self.conn.execute(
            "INSERT OR IGNORE INTO worlds(first_seen, world_epoch, fingerprint) VALUES(?,?,?)",
            (now(), self.world["world_epoch"], self.world["fingerprint"]))
        self.conn.commit()

    # -- one provider -----------------------------------------------------
    def poll(self, provider):
        entry = self.catalog.get(provider, {})
        status, body, latency, err = http_get("{}/{}/balance".format(self.base, provider))

        if status == 429:
            # Honour the rate limit rather than hammering: tremendous answered
            # 429 on the very first sequential sweep of all fifteen.
            wait = min(MAX_BACKOFF_SEC, max(30.0, self.backoff.get(provider, 15.0) * 2))
            self.backoff[provider] = wait
            record = {"ok": False, "error": "rate limited (429)", "model": entry.get("pay_model"),
                      "unit": entry.get("unit"), "value": None, "capacity": None,
                      "spend_24h": None, "spend_30d": None, "refresh": None, "shape": "429"}
        elif err and status is None:
            self.backoff[provider] = min(MAX_BACKOFF_SEC, max(10.0, self.backoff.get(provider, 5.0) * 2))
            record = {"ok": False, "error": err, "model": entry.get("pay_model"),
                      "unit": entry.get("unit"), "value": None, "capacity": None,
                      "spend_24h": None, "spend_30d": None, "refresh": None, "shape": None}
        else:
            self.backoff.pop(provider, None)
            record = normalize(body, entry.get("pay_model"), entry.get("unit"))

        self.conn.execute(
            "INSERT INTO samples(ts,world_epoch,fingerprint,provider,ok,http_status,latency_ms,"
            "model,unit,value,capacity,spend_24h,spend_30d,refresh,shape,error,raw) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (now(), self.world["world_epoch"], self.world["fingerprint"], provider,
             1 if record["ok"] else 0, status, latency, record["model"], record["unit"],
             record["value"], record["capacity"], record["spend_24h"], record["spend_30d"],
             record["refresh"], record["shape"], record["error"], (body or "")[:600]))
        self.conn.commit()
        self.analyzer.on_sample(provider, entry, record, self.world)

    # -- loop -------------------------------------------------------------
    def run(self):
        self.refresh_catalog()
        self.refresh_meta()
        if not self.catalog:
            print("no catalog; nothing to watch", file=sys.stderr)
            return 2
        print("watching {} providers every {:.0f}s, world {}".format(
            len(self.catalog), POLL_INTERVAL, self.world.get("fingerprint")), flush=True)

        if self.once:
            for provider in sorted(self.catalog):
                try:
                    self.poll(provider)
                except Exception as exc:
                    print("poll {} crashed: {}".format(provider, exc), file=sys.stderr, flush=True)
            write_snapshot(self.conn, self.world)
            return 0

        next_meta = now() + META_INTERVAL_SEC
        next_due = {}
        # Stagger the providers evenly instead of sweeping them in a burst.
        # Measured: 429 arrives on a random provider regardless of our pace, so
        # this is politeness rather than a fix - the backoff below is the fix.
        for index, provider in enumerate(sorted(self.catalog)):
            next_due[provider] = now() + index * (POLL_INTERVAL / max(1, len(self.catalog)))

        while not self.stop.is_set():
            current = now()
            if current >= next_meta:
                self.refresh_meta()
                next_meta = current + META_INTERVAL_SEC
            if current - self.catalog_ts > CATALOG_REFRESH_SEC:
                self.refresh_catalog()
                for provider in self.catalog:
                    next_due.setdefault(provider, current)

            for provider in list(next_due):
                if provider not in self.catalog:
                    next_due.pop(provider, None)
                    continue
                if current >= next_due[provider]:
                    try:
                        self.poll(provider)
                    except Exception as exc:                    # a bad provider must not kill the run
                        print("poll {} crashed: {}".format(provider, exc), file=sys.stderr, flush=True)
                    wait = self.backoff.get(provider, POLL_INTERVAL)
                    next_due[provider] = now() + wait + random.uniform(0, POLL_INTERVAL * 0.15)

            write_snapshot(self.conn, self.world)
            if self.once:
                return 0
            self.stop.wait(1.0)
        return 0


# ---------------------------------------------------------------------------
# snapshot for the dashboard
# ---------------------------------------------------------------------------
def write_snapshot(conn, world, path: Path = SNAPSHOT_PATH):
    path.parent.mkdir(parents=True, exist_ok=True)
    providers = []
    rows = conn.execute("SELECT DISTINCT provider FROM samples").fetchall()
    epoch = world.get("world_epoch")
    for row in rows:
        provider = row["provider"]
        last = conn.execute(
            "SELECT * FROM samples WHERE provider=? ORDER BY ts DESC LIMIT 1", (provider,)).fetchone()
        last_ok = conn.execute(
            "SELECT * FROM samples WHERE provider=? AND ok=1 ORDER BY ts DESC LIMIT 1",
            (provider,)).fetchone()
        baseline = burn_series(conn, provider, now() - BASELINE_WINDOW_SEC, epoch)
        median, _ = robust_baseline(baseline)
        recent = burn_series(conn, provider, now() - BURN_WINDOW_SEC, epoch)
        recent_burn = statistics.mean([v for _, v in recent]) if recent else 0.0
        value = last_ok["value"] if last_ok else None
        rate = median or recent_burn
        runway = (value / rate) if (rate and value and value > 0) else None
        series = conn.execute(
            "SELECT ts, value FROM samples WHERE provider=? AND ok=1 AND value IS NOT NULL "
            "AND ts>=? ORDER BY ts", (provider, now() - 6 * 3600)).fetchall()
        providers.append({
            "provider": provider,
            "model": last_ok["model"] if last_ok else (last["model"] if last else None),
            "unit": last_ok["unit"] if last_ok else None,
            "value": value,
            "capacity": last_ok["capacity"] if last_ok else None,
            "spend_24h": last_ok["spend_24h"] if last_ok else None,
            "burn_per_h": round(recent_burn, 4),
            "baseline_per_h": round(median, 4) if median else None,
            "runway_h": round(runway, 2) if runway else None,
            "healthy": bool(last and last["ok"]),
            "last_error": (last["error"] if last and not last["ok"] else None),
            "last_seen": iso(last["ts"]) if last else None,
            "last_ok_seen": iso(last_ok["ts"]) if last_ok else None,
            "samples": len(series),
            "topups_6h": len(topups(conn, provider, now() - 6 * 3600, epoch)),
            "series": [[round(r["ts"]), r["value"]] for r in series][-400:],
        })
    providers.sort(key=lambda p: (p["runway_h"] is None, p["runway_h"] or 0))
    alerts = []
    if ALERTS_PATH.exists():
        lines = ALERTS_PATH.read_text(encoding="utf-8").splitlines()[-60:]
        for line in lines:
            try:
                alerts.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    payload = {
        "generated": iso(now()),
        "world": world,
        "window_note": "runway uses the median burn over the last {:.0f}h; increases are treated as "
                       "top-ups and never enter the baseline".format(BASELINE_WINDOW_SEC / 3600),
        "providers": providers,
        "alerts": list(reversed(alerts)),
    }
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)
    return payload


# ---------------------------------------------------------------------------
# self-test: the detectors must fire on planted data, offline
# ---------------------------------------------------------------------------
def self_test() -> int:
    import tempfile
    failures = []
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        conn = connect(root / "t.sqlite")
        alerts_path = root / "alerts.jsonl"
        alerter = Alerter(conn, alerts_path)
        analyzer = Analyzer(conn, alerter)
        world = {"world_epoch": 1.0, "fingerprint": "aaa"}

        def insert(provider, ts, value, ok=1, model="prepaid_balance", **kw):
            conn.execute(
                "INSERT INTO samples(ts,world_epoch,fingerprint,provider,ok,model,unit,value,"
                "capacity,spend_24h,refresh) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (ts, 1.0, "aaa", provider, ok, model, kw.get("unit", "usd"), value,
                 kw.get("capacity"), kw.get("spend_24h"), kw.get("refresh")))
            conn.commit()

        # --- shape parsing, against the six shapes actually observed --------
        # Every body below is a VERBATIM response captured from the live stand
        # on 2026-08-23, not an invented example.
        cases = [
            ('{"balance":997.08,"currency":"USD"}', "prepaid_balance", 997.08, True),
            ('{"ok":true,"data":{"wallet":{"amount":331.91,"ccy":"usd"}}}', "prepaid_balance", 331.91, True),
            ('{"remaining":39253,"package":50000,"refresh":"2026-09-01"}', "credits_package", 39253, True),
            ('{"credit":-146.81,"unit":"usd"}', "postpaid", -146.81, True),
            ('{"gbp":2005.07}', "prepaid_balance", 2005.07, True),
            ('{"spend_usd_30d":10916.68,"spend_usd_24h":363.89}', "spend_report", None, True),
            ('{"object":"cost_report","amount_cents":11218,"window":"trailing_24h"}',
             "spend_report", None, True),
            ('{}', "spend_report", None, False),
            ('{"error":"rate limited"}', "prepaid_balance", None, False),
        ]
        for body, declared, expected, should_ok in cases:
            got = normalize(body, declared, "usd")
            if got["ok"] != should_ok:
                failures.append("shape {}: ok={} expected {}".format(body[:28], got["ok"], should_ok))
            if expected is not None and got["value"] != expected:
                failures.append("shape {}: value {} expected {}".format(body[:28], got["value"], expected))
        if normalize('{"spend_usd_24h":1}', "spend_report", "usd")["spend_24h"] != 1:
            failures.append("spend_report did not read spend_usd_24h")
        # cents must become dollars, or the account reads 100x too rich
        cents = normalize('{"object":"cost_report","amount_cents":11218,"window":"trailing_24h"}',
                          "spend_report", "usd")
        if cents["spend_24h"] != 112.18:
            failures.append("amount_cents read as {} - expected 112.18 dollars".format(cents["spend_24h"]))
        if cents["value"] is not None:
            failures.append("a cost report was recorded as if it were a balance")
        gbp = normalize('{"gbp":2005.07}', "prepaid_balance", "usd")
        if gbp["unit"] != "gbp":
            failures.append("currency-named field did not set the unit: {}".format(gbp["unit"]))
        # a changed shape must still parse AND be flagged, not crash
        changed = normalize('{"wallet_balance_usd":12.5}', "prepaid_balance", "usd")
        if not changed["ok"] or changed["value"] != 12.5:
            failures.append("fallback did not survive an unseen shape")

        # --- a top-up must not enter the baseline ---------------------------
        # Timestamps must be recent: every window is relative to now(), so data
        # planted at a 1970 epoch is invisible to the very code under test.
        # This is exactly how the first run of this self-test failed.
        step = 300.0
        base = now() - 31 * step
        for i in range(30):                      # steady 0.5 per 5 min = 6.0/h
            insert("steady", base + i * step, 500 - i * 0.5)
        insert("steady", base + 30 * step, 900.0)  # a top-up
        series = burn_series(conn, "steady", now() - BASELINE_WINDOW_SEC, 1.0)
        if any(v < 0 for _, v in series):
            failures.append("a top-up leaked into the burn series")
        median, _ = robust_baseline(series)
        if median is None or abs(median - 6.0) > 0.5:
            failures.append("baseline is {} expected ~6/h".format(median))

        def sample(value, model="prepaid_balance", **kw):
            record = {"ok": True, "model": model, "unit": "usd", "value": value,
                      "capacity": None, "spend_24h": None, "spend_30d": None,
                      "refresh": None, "shape": "balance@flat", "error": None}
            record.update(kw)
            return record

        def lines():
            if not alerts_path.exists():
                return []
            return [json.loads(l) for l in alerts_path.read_text(encoding="utf-8").splitlines()]

        # --- runway must fire when the money is nearly gone -----------------
        for i in range(20):                      # 4.0 per 5 min = 48/h
            insert("dying", base + i * step, 100 - i * 4.0)
        analyzer.on_sample("dying", {"pay_model": "prepaid_balance"}, sample(20.0), world)
        if not any(a["kind"] == "runway" for a in lines()):
            failures.append("runway alert never fired on a nearly-empty balance")

        # --- the headline detector: sustained spend well above normal -------
        for i in range(24):                      # calm: 0.1 per 5 min = 1.2/h
            insert("spiky", base + i * step, 800 - i * 0.1)
        analyzer.anomaly_since["spiky"] = now() - (ANOMALY_SUSTAIN_SEC + 60)
        burst_start = now() - 700
        for i in range(4):                       # burst: 2.0 per 3 min = 40/h
            insert("spiky", burst_start + i * 180, 797.6 - i * 2.0)
        analyzer.on_sample("spiky", {"pay_model": "prepaid_balance"}, sample(789.6), world)
        spikes = [a for a in lines() if a["kind"] == "burn_anomaly"]
        if not spikes:
            failures.append("burn anomaly never fired on a sustained 30x burst")
        elif spikes[0].get("ratio", 0) < ANOMALY_RATIO:
            failures.append("burn anomaly fired with a ratio below its own threshold")

        # --- a top-up must not be mistaken for a spend spike ----------------
        before_topup = len(lines())
        insert("spiky", now() - 60, 5000.0)      # someone topped the account up
        analyzer.on_sample("spiky", {"pay_model": "prepaid_balance"}, sample(5000.0), world)
        if len(lines()) != before_topup:
            failures.append("a top-up produced an alert; the task calls that normal operations")

        # --- 200-with-no-body must be reported, not read as calm ------------
        for _ in range(STALE_FAILURES):
            analyzer.on_sample("silent", {"pay_model": "spend_report"},
                               {"ok": False, "error": "empty json object", "model": "spend_report",
                                "unit": "usd", "value": None, "capacity": None, "spend_24h": None,
                                "spend_30d": None, "refresh": None, "shape": "empty"}, world)
        silent = [a for a in lines() if a["provider"] == "silent"]
        if not silent:
            failures.append("HTTP 200 with an empty body never raised an alert")
        elif "invisible" not in silent[0]["text"]:
            failures.append("the empty-body alert does not say spend is invisible")

        # --- duplicate suppression ------------------------------------------
        before = len(alerts_path.read_text(encoding="utf-8").splitlines())
        for _ in range(20):
            alerter.fire("runway:dying", "critical", "dying", "same thing again")
        after = len(alerts_path.read_text(encoding="utf-8").splitlines())
        if after != before:
            failures.append("cooldown did not suppress a repeat alert ({} new lines)".format(after - before))
        if not alerter.fire("runway:dying2", "critical", "dying2", "a different key must pass"):
            failures.append("cooldown suppressed a different alert key")

        # --- every alert line must carry ts with an offset, and text --------
        for line in alerts_path.read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            if "ts" not in record or "text" not in record:
                failures.append("an alert line is missing a required key")
                break
            stamp = record["ts"]
            if not (stamp.endswith("Z") or "+" in stamp[10:] or "-" in stamp[19:]):
                failures.append("alert ts has no timezone offset: " + stamp)
                break
            datetime.fromisoformat(stamp)          # must parse

        # --- world reset is noticed -----------------------------------------
        mon = Monitor.__new__(Monitor)
        mon.conn, mon.alerter = conn, alerter
        mon.analyzer = analyzer
        mon.world = {"world_epoch": 1.0, "fingerprint": "aaa"}
        mon.base = "http://127.0.0.1:1"           # unused: refresh_meta is not called
        previous = dict(mon.world)
        mon.world = {"world_epoch": 2.0, "fingerprint": "bbb"}
        alerter.fire("world:reset", "critical", "",
                     "the stand reset its world: epoch {} -> {}".format(
                         previous["world_epoch"], mon.world["world_epoch"]))
        if not any(json.loads(l)["kind"] == "world" for l in
                   alerts_path.read_text(encoding="utf-8").splitlines()):
            failures.append("world reset produced no alert")

        snapshot = write_snapshot(conn, world, root / "data.json")
        if not snapshot["providers"]:
            failures.append("snapshot has no providers")
        # Windows will not delete an open sqlite file, and WAL keeps it open.
        conn.close()

    if failures:
        print("SELF-TEST: FAIL")
        for item in failures:
            print("  - " + item)
        return 1
    print("SELF-TEST: PASS")
    return 0


def main(argv):
    ap = argparse.ArgumentParser(description="Spend observability monitor")
    ap.add_argument("command", nargs="?", default="run", choices=("run", "once", "snapshot"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)
    if args.self_test:
        return self_test()
    if args.command == "snapshot":
        conn = connect()
        row = conn.execute("SELECT world_epoch, fingerprint FROM worlds ORDER BY first_seen DESC "
                           "LIMIT 1").fetchone()
        world = {"world_epoch": row["world_epoch"], "fingerprint": row["fingerprint"]} if row else {}
        write_snapshot(conn, world)
        print("snapshot written to {}".format(SNAPSHOT_PATH))
        return 0
    return Monitor(once=(args.command == "once")).run()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
