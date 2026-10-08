# Ledger reconciliation

This directory contains a deterministic, offline ledger exercise.

- `model.py` is the command-driven transition model. It owns state changes and event emission.
- `reconcile.py` is an independent event fold. It validates strict schemas, canonical headers/order, emitters, integer ranges, liabilities, and solvency.
- `test_ledger.py` contains the focused regression tests.
- `run_tests.py` runs those tests and generates 120 deterministic lifecycle fixtures, independently reconciles every fixture, and writes exact-count artifacts under `generated/`.

## Run

```sh
python3 run_tests.py
```

A successful run exits 0 and writes:

- `generated/fixtures/case-000.json` through `case-119.json`
- `generated/trace.jsonl` (one record per case)
- `generated/report.json` (counts and captured unittest output)

The generator uses no network, wallet, chain, or external service. Failed withdrawal attempts are included in selected cases to exercise the model's rollback behavior; they intentionally emit no ledger events.

All monetary and counter values remain Python `int` values. The reconciler does not import the model.
