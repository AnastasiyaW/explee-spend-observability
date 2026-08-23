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
     '        elapsed += seconds\n        drop = prev["value"] - cur["value"]',
     '        drop = prev["value"] - cur["value"]\n        if drop > 0: elapsed += seconds'),
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
     "        if median <= 0 or recent / median < ANOMALY_RATIO:",
     "        if True:"),
    ("M6 world key drops the fingerprint",
     'AND ts>=? AND world_epoch IS ? AND fingerprint IS ? ORDER BY ts",\n'
     '        (provider, since, world.get("world_epoch"), world.get("fingerprint"))',
     'AND ts>=? AND world_epoch IS ? ORDER BY ts",\n'
     '        (provider, since, world.get("world_epoch"))'),
    ("M7 top-ups counted as spending",
     '        drop = prev["value"] - cur["value"]\n        if drop > 0:\n            spent += drop',
     '        spent += abs(prev["value"] - cur["value"])'),
    ("M8 empty-body at HTTP 200 treated as fine",
     "        if streak < STALE_FAILURES:\n            return",
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
