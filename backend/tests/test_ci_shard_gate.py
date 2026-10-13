"""Unit tests for scripts/ci_shard_gate.py."""
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import ci_shard_gate  # noqa: E402

ALL = [f"t.py::test_{i}" for i in range(7)]


def _hash(ids):
    return hashlib.sha256("\n".join(sorted(ids)).encode()).hexdigest()


def _write(tmp_path, total=3, tweak=None):
    reports = []
    for i in range(total):
        sel = ALL[i::total]
        reports.append(
            {"shard": f"{i}/{total}", "collected": len(ALL), "selected": len(sel),
             "collected_hash": _hash(ALL), "nodeids": sel}
        )
    if tweak:
        tweak(reports)
    for i, r in enumerate(reports):
        (tmp_path / f"r{i}.json").write_text(json.dumps(r))
    return tmp_path


def test_ok(tmp_path):
    assert ci_shard_gate.check(_write(tmp_path), 3) == []


def test_missing_shard(tmp_path):
    d = _write(tmp_path, tweak=lambda r: r.pop())
    assert any("expected shards" in p for p in ci_shard_gate.check(d, 3))


def test_overlapping_shards(tmp_path):
    def tweak(r):
        r[1]["nodeids"].append(r[0]["nodeids"][0])
        r[1]["selected"] += 1
        r[1]["collected"] = r[0]["collected"]
    d = _write(tmp_path, tweak=tweak)
    assert any("overlap" in p for p in ci_shard_gate.check(d, 3))


def test_test_missing_from_every_shard(tmp_path):
    def tweak(r):
        r[2]["nodeids"].pop()
    d = _write(tmp_path, tweak=tweak)
    assert any("no shard" in p for p in ci_shard_gate.check(d, 3))


def test_differing_collected_sets(tmp_path):
    def tweak(r):
        r[1]["collected_hash"] = _hash(ALL + ["t.py::extra"])
    d = _write(tmp_path, tweak=tweak)
    assert any("identical set" in p for p in ci_shard_gate.check(d, 3))
