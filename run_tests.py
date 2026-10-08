"""Run the unit suite and deterministic model/reconciler lifecycle corpus.

The transition model creates events; reconcile.py independently folds those events.
Generated artifacts are intentionally reproducible and are ignored by git.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
GENERATED = ROOT / "generated"
FIXTURES = GENERATED / "fixtures"
TRACE = GENERATED / "trace.jsonl"
REPORT = GENERATED / "report.json"
CASE_COUNT = 120


def fixture_for(case_id: int) -> tuple[dict, str]:
    # Keep scenarios varied while staying inside the existing model API.
    from model import Model, block_hash
    from reconcile import reconcile

    m = Model()
    creator = f"creator-{case_id % 5}"
    winner = f"winner-{case_id % 7}"
    recipient = f"recipient-{case_id % 11}"
    bid = case_id + 1
    reward = 10 + (case_id * 37 % 991)
    deadline = 1_000 + case_id
    m.create(bid, creator, reward, deadline)
    scenario = case_id % 6
    if scenario == 0:
        m.award(bid, winner, creator)
        m.withdraw(winner, recipient, fail=True)  # rollback is intentionally eventless
        m.withdraw(winner, recipient)
    elif scenario == 1:
        m.award(bid, winner, creator)
    elif scenario == 2:
        m.expire(bid, deadline + 604801)
        m.withdraw(creator, recipient)
    elif scenario == 3:
        m.donate(f"donor-{case_id % 13}", 3 + case_id % 19)
    elif scenario == 4:
        m.award(bid, winner, creator)
        m.donate(f"donor-{case_id % 13}", 1 + case_id % 23)
    else:
        m.expire(bid, deadline + 604801)

    fixture = {
        "events": m.events,
        "snapshot": m.snapshot(),
        "anchor": {"number": m.block, "hash": block_hash(m.block)},
        "headers": {str(i): block_hash(i) for i in range(1, m.block + 1)},
    }
    # The call is part of generation: every emitted corpus member is checked.
    reconcile(fixture, json.loads((ROOT / "escrow-abi.json").read_text()))
    return fixture, ["open", "award+withdraw", "expire+withdraw", "open+donate", "award+donate", "expire"][scenario]


def run() -> int:
    GENERATED.mkdir(exist_ok=True)
    FIXTURES.mkdir(exist_ok=True)
    test = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-v"],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )

    records = []
    reconciled = 0
    failures = []
    for case_id in range(CASE_COUNT):
        try:
            fixture, scenario = fixture_for(case_id)
            (FIXTURES / f"case-{case_id:03d}.json").write_text(
                json.dumps(fixture, sort_keys=True, indent=2) + "\n"
            )
            from reconcile import reconcile
            result = reconcile(fixture, json.loads((ROOT / "escrow-abi.json").read_text()))
            reconciled += 1
            records.append({
                "case_id": case_id,
                "scenario": scenario,
                "status": "ok",
                "event_count": len(fixture["events"]),
                "surplus": result["surplus"],
            })
        except Exception as exc:  # report every case failure without hiding it
            failures.append({"case_id": case_id, "error": f"{type(exc).__name__}: {exc}"})
            records.append({"case_id": case_id, "status": "error", "error": str(exc)})

    TRACE.write_text("".join(json.dumps(record, sort_keys=True) + "\n" for record in records))
    report = {
        "schema": 1,
        "deterministic_seed": "case_id-sequence-v1",
        "requested_cases": CASE_COUNT,
        "generated_cases": len(records),
        "reconciled_ok": reconciled,
        "reconciliation_failures": len(failures),
        "unit_tests_returncode": test.returncode,
        "unit_tests_passed": test.returncode == 0,
        "unit_test_count": 3,
        "failures": failures,
        "status": "PASS" if test.returncode == 0 and not failures and len(records) == CASE_COUNT else "FAIL",
    }
    REPORT.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")
    print(json.dumps({k: report[k] for k in (
        "status", "generated_cases", "reconciled_ok", "reconciliation_failures", "unit_tests_returncode"
    )}, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(run())
