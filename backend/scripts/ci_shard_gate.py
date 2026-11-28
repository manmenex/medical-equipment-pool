"""Prove a sharded CI test run covered every collected test exactly once.

Each shard job writes the JSON report described in tests/conftest.py's
`pytest_collection_modifyitems`. Every shard passing is not enough on its
own: a shard that never ran, or a sharding bug, would leave tests unrun
while CI showed green. This fails unless every shard 0..total-1 reported,
they all collected the same number of tests, and their selections add up
to exactly that number.

Usage: python scripts/ci_shard_gate.py <directory-of-shard-reports> <total>
"""
import hashlib
import json
import sys
from pathlib import Path


def check(report_dir: Path, total: int) -> list[str]:
    reports = [json.loads(p.read_text()) for p in sorted(report_dir.rglob("*.json"))]
    problems = []
    seen = sorted(int(r["shard"].split("/")[0]) for r in reports)
    if seen != list(range(total)):
        problems.append(f"expected shards 0..{total - 1}, got reports for {seen}")
    if any(int(r["shard"].split("/")[1]) != total for r in reports):
        problems.append(f"a shard ran with a total other than {total}")
    collected = {r["collected"] for r in reports}
    if len(collected) != 1:
        problems.append(f"shards collected different test counts: {sorted(collected)}")
    elif sum(r["selected"] for r in reports) != collected.pop():
        problems.append("shard selections do not add up to the collected count")
    hashes = {r.get("collected_hash") for r in reports}
    if len(hashes) != 1 or None in hashes:
        problems.append("shards did not all collect the identical set of tests")
    ids = [i for r in reports for i in r.get("nodeids", [])]
    if len(ids) != len(set(ids)):
        problems.append("shards overlap: some tests were selected by more than one shard")
    elif len(hashes) == 1 and None not in hashes:
        union_hash = hashlib.sha256("\n".join(sorted(ids)).encode()).hexdigest()
        if union_hash != next(iter(hashes)):
            problems.append("union of shard selections differs from the collected set (a test ran in no shard)")
    return problems


def main() -> int:
    report_dir, total = Path(sys.argv[1]), int(sys.argv[2])
    problems = check(report_dir, total)
    for problem in problems:
        print(f"FAIL: {problem}")
    if not problems:
        print(f"OK: {total} shards cover every collected test exactly once")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
