# TDD record

The existing focused tests were run before adding the runner and corpus: `python3 -m unittest -v` passed all 3 tests.

The runner was then designed around the existing public model/reconciler APIs rather than changing either implementation. Its verification contract is:

1. Run `unittest discover` in the repository directory.
2. Build deterministic lifecycle fixtures from `case_id` only.
3. Reconcile each fixture with the independent `reconcile()` implementation.
4. Persist one JSONL trace record per case and a report containing exact counts.
5. Exit non-zero if unit tests or any generated reconciliation fail.

The generated corpus covers open bounties, awards, expiry/refund, successful withdrawals, failed-withdraw rollback followed by success, and token donations/surplus. `generated/report.json` is the executable evidence for the latest run.
