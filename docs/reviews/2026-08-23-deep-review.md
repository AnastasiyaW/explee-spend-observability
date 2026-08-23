# Focused deep review — 2026-08-23

Scope: `spend_monitor.py`, its deployment wrapper, and mutation proof. This is
the repair review for the confirmed runtime-boundary findings; it does not
authorize deletion of historical samples.

| Finding | Triage | Repair |
|---|---|---|
| Snapshot queries could blend worlds and present an old successful row as current/healthy. | Fixed — correctness | Provider discovery, latest rows, spend-report count, and series all key on `(world_epoch, fingerprint)`; a reset fixture proves old data cannot surface. |
| Response-shape history crossed worlds and could suppress a real schema-change alert after reset. | Fixed — correctness | Shape history now uses the same complete world identity; a prior-world `A/B` plus current-world `A → B` fixture proves the alert fires. |
| `/meta` accepted partial identity and startup could collect NULL-world samples. | Fixed — correctness | Both identifiers are required; startup refuses polling otherwise, while later invalid meta retains the last complete identity. |
| Concurrent collectors could mutate one SQLite/history stream; snapshot temp names collided. | Fixed — operational | Nonblocking cross-platform advisory lock and process-unique temp files plus atomic replacement. |
| 5xx and malformed 200 responses bypassed backoff; catalog failure retried every loop tick. | Fixed — availability | Every non-valid response backs off until a valid parsed response; catalog has its own bounded retry schedule. |
| `api_stats` had no ts-leading access path or direct test; mutation runner could accept a bad baseline/survivors. | Fixed — proof/performance | Migration-safe `samples(ts)` index, stats assertions, isolated mutant temp directory, mandatory green baseline, and nonzero survivor exit. |
| Remote deploy overwrote the live file before candidate proof. | Fixed — release safety | `pipefail`; unique staged candidate; compile and self-test before same-directory atomic promotion, then restart. |

Focused verification:

```text
python spend_monitor.py --self-test     # PASS
python mutation_test.py                 # 12/12 mutants killed; exit 0
python -m py_compile spend_monitor.py mutation_test.py  # exit 0
```

The deploy script’s embedded program is normalized-byte-equal to
`spend_monitor.py`. Historical sample retention/deletion remains explicitly
deferred: no automated deletion was added.
