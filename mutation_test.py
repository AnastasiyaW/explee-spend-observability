"""Prove the monitor self-test rejects the defects it claims to cover."""
import io
import pathlib
import subprocess
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

SRC = pathlib.Path(__file__).with_name("spend_monitor.py")

MUTANTS = [
    ("M1 rate ignores flat time (the shipped 3x bug)",
     '    spent, elapsed = 0.0, 0.0\n'
     '    for prev, cur in zip(rows, rows[1:]):\n'
     '        seconds = cur["ts"] - prev["ts"]\n'
     '        if seconds <= 0:\n'
     '            continue\n'
     '        elapsed += seconds',
     '    spent, elapsed = 0.0, 0.0\n'
     '    for prev, cur in zip(rows, rows[1:]):\n'
     '        seconds = cur["ts"] - prev["ts"]\n'
     '        if seconds <= 0:\n'
     '            continue\n'
     '        elapsed += 0.0 if prev["value"] <= cur["value"] else seconds'),
    ("M2 clear() forgets the cooldown (the spam bug)",
     "SET last_level='resolved' WHERE key=?",
     "SET last_level='resolved', last_ts=0 WHERE key=?"),
    ("M3 no warm-up gate on runway",
     "        warm = samples >= WARMUP_BURN_SAMPLES and bucket_count >= 3",
     "        warm = True"),
    ("M4 shape-change detector disabled",
     '        if shape_history and record["shape"] and record["shape"] not in shape_history:',
     "        if False:"),
    ("M5 spend-report detector disabled",
     "        if recent is None or median <= 0 or recent / median < ANOMALY_RATIO:",
     "        if True:"),
    ("M6 world key drops the fingerprint",
     'AND ts>=? AND world_epoch IS ? AND fingerprint IS ? ORDER BY ts",\n'
     '        (provider, since, world.get("world_epoch"), world.get("fingerprint"))',
     'AND ts>=? AND world_epoch IS ? ORDER BY ts",\n'
     '        (provider, since, world.get("world_epoch"))'),
    ("M7 top-ups counted as spending",
     '        drop = prev["value"] - cur["value"]\n'
     '        if drop > 0:\n'
     '            spent += drop\n'
     '    if elapsed <= 0:',
     '        spent += abs(prev["value"] - cur["value"])\n'
     '    if elapsed <= 0:'),
    ("M8 empty-body at HTTP 200 treated as fine",
     "        self.fail_streak[provider] = streak\n"
     "        if streak < STALE_FAILURES:\n            return",
     "        self.fail_streak[provider] = streak\n"
     "        if True:\n            return"),
    ("M9 incomplete meta accepted",
     'if not isinstance(meta, dict) or "world_epoch" not in meta or "fingerprint" not in meta:',
     'if not isinstance(meta, dict) or "world_epoch" not in meta:'),
    ("M10 snapshot provider discovery crosses worlds",
     '"SELECT DISTINCT provider FROM samples WHERE world_epoch IS ? AND fingerprint IS ?"',
     '"SELECT DISTINCT provider FROM samples"'),
    ("M11 invalid responses clear provider backoff",
     '        if record["ok"]:\n            self.backoff.pop(provider, None)',
     '        if True:\n            self.backoff.pop(provider, None)'),
    ("M12 shape history crosses stand worlds",
     '        "AND world_epoch IS ? AND fingerprint IS ?",\n        (provider, world.get("world_epoch"), world.get("fingerprint"))).fetchall()}',
     '        "",\n        (provider,)).fetchall()}'),
    ("M13 runway divides by the robust median again",
     "        long_run = window_rate(self.conn, provider, world)",
     "        long_run = median"),
    ("M14 the spend-report sustain clock is never reset",
     '            self.anomaly_since.pop("spend:" + provider, None)\n'
     '            self.alerter.clear("spend_spike:" + provider)',
     '            self.alerter.clear("spend_spike:" + provider)'),
    ("M15 a burn happening now is hidden by the long-run average",
     '        if sustained_burn:\n'
     '            options.append((sustained_burn, "at the rate of the last {:.0f} min".format(\n'
     '                BURN_WINDOW_SEC / 60)))',
     "        pass"),
    ("M16 one step counts as a burn",
     "    enough = drops >= ACUTE_MIN_DROPS or (drops >= 2 and falling >= ACUTE_MIN_FRACTION)",
     "    enough = drops >= 1"),
    ("M17 an empty balance raises nothing",
     "        if warm and not postpaid and value is not None and value <= 0:",
     "        if False:"),
    ("M18 postpaid debt alerts with no threshold",
     "            if ratio >= ANOMALY_RATIO:\n"
     '                self.alerter.fire(\n'
     '                    "debt:" + provider, "warn", provider,',
     "            if True:\n"
     '                self.alerter.fire(\n'
     '                    "debt:" + provider, "warn", provider,'),
    ("M19 an outage keeps the sustain clock running",
     "            self.anomaly_since.pop(provider, None)\n"
     '            self.anomaly_since.pop("spend:" + provider, None)\n'
     "            self._health(provider, record)",
     "            self._health(provider, record)"),
    ("M20 a new world inherits the old world's cooldown",
     '            self.conn.execute("DELETE FROM alert_state")',
     "            pass"),
    ("M21 spend-report baseline goes back to its own derivative",
     "        median = current / window_hours",
     "        median = 0.0"),
    ("M23 runway fires on a postpaid account",
     "        if warm and not postpaid and options and draining and value is not None and value > 0:",
     "        if warm and options and draining and value is not None and value > 0:"),
    ("M24 the acute test counts polls instead of the balance",
     "    enough = drops >= ACUTE_MIN_DROPS or (drops >= 2 and falling >= ACUTE_MIN_FRACTION)",
     "    enough = drops >= ACUTE_MIN_DROPS"),
    ("M25 the exhaustion alert shares runway's cooldown",
     '            self.alerter.fire("exhausted:" + provider, "critical", provider,',
     '            self.alerter.fire("runway:" + provider, "critical", provider,'),
    # The anchor carries the line above it: this exact expression also appears
    # in the anomaly branch, and mutating that one instead reported SURVIVED
    # while measuring something else.
    ("M26 postpaid debt treats a zero baseline as no baseline",
     "            # The balance branch above already handles that with math.inf.\n"
     "            ratio = sustained_burn / median if median > 0 else math.inf",
     "            ratio = sustained_burn / median if median > 0 else 0.0"),
    ("M27 runway ignores whether the account is going down at all",
     "        draining = net is None or net > 0 or bool(sustained_burn)",
     "        draining = True"),
    ("M28 the monitor goes blind in silence",
     "        if streak < STALE_FAILURES:\n            return\n        self.alerter.fire(\n"
     '            key, "critical", "",',
     "        if True:\n            return\n        self.alerter.fire(\n"
     '            key, "critical", "",'),
    ("M29 spend accrual measured from the endpoints again",
     "            accrued = 0.0\n"
     "            for previous, current_row in zip(subset, subset[1:]):\n"
     "                step = current_row[\"v\"] - previous[\"v\"]\n"
     "                if step > 0:\n"
     "                    accrued += step\n"
     "            return accrued / (seconds / 3600.0)",
     "            return max(0.0, subset[-1][\"v\"] - subset[0][\"v\"]) / (seconds / 3600.0)"),
    ("M22 a stopped collector still reads healthy",
     '            "healthy": bool(last and last["ok"]\n'
     '                            and now() - last["ts"] < MAX_BACKOFF_SEC + STALE_FAILURES * POLL_INTERVAL),',
     '            "healthy": bool(last and last["ok"]),'),
]


def run(command):
    return subprocess.run(command, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=300)


def main() -> int:
    baseline = run([sys.executable, str(SRC), "--self-test"])
    if baseline.returncode != 0 or "SELF-TEST: PASS" not in baseline.stdout:
        print("BASELINE FAILED; refusing to score mutants")
        print((baseline.stdout + baseline.stderr).strip())
        return 1

    source = SRC.read_text(encoding="utf-8")
    survivors = 0
    with tempfile.TemporaryDirectory(prefix="spend_monitor_mutants_") as directory:
        work = pathlib.Path(directory) / "spend_monitor_mutant.py"
        for name, old, new in MUTANTS:
            if old not in source:
                print("  {:<52} ANCHOR MISSING - mutation not applied".format(name))
                survivors += 1
                continue
            # An anchor that matches twice mutates whichever site comes first,
            # which is not the one the mutant is named after. M26 spent a round
            # reporting SURVIVED while measuring the anomaly branch instead of
            # the debt branch, because both had grown the same line.
            if source.count(old) > 1:
                print("  {:<52} ANCHOR AMBIGUOUS ({} matches) - not applied".format(
                    name, source.count(old)))
                survivors += 1
                continue
            work.write_text(source.replace(old, new, 1), encoding="utf-8")
            proc = run([sys.executable, str(work), "--self-test"])
            survived = proc.returncode == 0 and "SELF-TEST: PASS" in proc.stdout
            if survived:
                survivors += 1
            print("  {:<52} {}".format(
                name, "SURVIVED - suite is blind here" if survived else "killed"))

    print()
    print("{} of {} mutants killed".format(len(MUTANTS) - survivors, len(MUTANTS)))
    return 1 if survivors else 0


if __name__ == "__main__":
    sys.exit(main())
