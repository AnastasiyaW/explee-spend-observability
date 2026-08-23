"""Does the rewritten self-test actually bite?

Each mutant reintroduces one defect the independent verifier found. A mutant
that SURVIVES means the suite is blind to that defect - which is what the
previous suite was for three of five.
"""
import io
import pathlib
import shutil
import tempfile
import subprocess
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

SRC = pathlib.Path(__file__).with_name("spend_monitor.py")
WORK = pathlib.Path(tempfile.gettempdir()) / "spend_monitor_mutant.py"

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
]

source = SRC.read_text(encoding="utf-8")
survivors = 0
for name, old, new in MUTANTS:
    if old not in source:
        print("  {:<52} ANCHOR MISSING - mutation not applied".format(name))
        survivors += 1
        continue
    WORK.write_text(source.replace(old, new, 1), encoding="utf-8")
    proc = subprocess.run([sys.executable, str(WORK), "--self-test"],
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=300)
    passed = "SELF-TEST: PASS" in (proc.stdout or "")
    if passed:
        survivors += 1
    print("  {:<52} {}".format(name, "SURVIVED - suite is blind here" if passed else "killed"))

print()
print("{} of {} mutants killed".format(len(MUTANTS) - survivors, len(MUTANTS)))
shutil.rmtree(WORK, ignore_errors=True) if WORK.is_dir() else WORK.unlink(missing_ok=True)
