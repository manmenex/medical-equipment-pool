# PR14B Pagination Index Evidence

Roadmap PR14 (PR14B slice — Pagination Performance), Repository-Owner-mandated evidence gate: no index/pagination design work was permitted to begin without `EXPLAIN (ANALYZE, BUFFERS)` evidence of a real query-plan problem. This document is that evidence, and the record of what migration `0011_pagination_ordering_indexes.py` is based on.

## Method

A local PostgreSQL 16 instance was seeded to the scale the original Backend Audit 5.2 finding was framed against (a hospital-wide asset register, since abandoned as this project's actual scope, but still a useful stress ceiling): **200,000 `equipment` rows, 1,000,000 `borrow_transactions` rows**. `created_at` was set to a realistic non-clustered distribution spread across ~2 years per row (`now() - random() * interval '730 days'`), not a tight batch-insert cluster — a first pass using the raw batch-insert default (`server_default=func.now()`, all rows within the same ~13-second seeding window) was discarded because it produced misleadingly pathological deep-cursor results (thousands of rows sharing an identical `created_at`) that would not occur in real usage, where each transaction is created at a genuinely distinct wall-clock moment.

Every query below is the literal query `app.crud.equipment.search()` / `app.crud.transaction.search()` issues (verified by reading the SQLAlchemy statement construction directly), not an approximation.

## Before (no index) vs. after (`(created_at DESC, id DESC)` composite index)

| # | Query | Before: plan | Before: time | After: plan | After: time |
|---|---|---|---|---|---|
| 1 | Equipment first page, no filter (`GET /equipment`) | Parallel Seq Scan + top-N Sort | 55.5ms | Index Scan | 0.31ms |
| 2 | Equipment first page + `status` filter | Parallel Seq Scan + top-N Sort | 49.8ms | Index Scan | 0.05ms |
| 3 | Equipment deep cursor, offset 100,000 of 200,000 | Parallel Seq Scan + top-N Sort | 45.5ms | Index Scan + Filter (100,001 rows removed) | **85.9ms (worse)** |
| 4 | Transactions first page, no filter (`GET /transactions`) | Seq Scan + top-N Sort | 134.4ms | Index Scan | 0.23ms |
| 5 | Transactions first page + `ward_id` filter | Index Scan on existing `ix_borrow_transactions_ward_id` + Sort | 0.06ms | unchanged (pre-existing index already used; this migration doesn't touch it) | 0.06ms |
| 6 | Transactions first page + `borrowed_at` date-range filter | Seq Scan + top-N Sort | 205.5ms | Index Scan | 0.05ms |
| 8 | Equipment `COUNT(*)` (informational — Finding 5.2, explicitly **out of scope**, not to be changed) | Parallel Seq Scan + Aggregate | 46.9ms | unchanged — no index covers this path | unchanged |

Query 1's exact plan, before:
```
Limit (actual time=52.526..55.357 rows=26)
  -> Gather Merge (Workers Launched: 2)
       -> Sort (Sort Method: top-N heapsort)
            Sort Key: created_at DESC, id DESC
            -> Parallel Seq Scan on equipment
                 Filter: (deleted_at IS NULL)
Execution Time: 55.520 ms
```
Query 1's exact plan, after:
```
Limit (actual time=0.043..0.290 rows=26)
  -> Index Scan using ix_equipment_created_at_id on equipment
       Filter: (deleted_at IS NULL)
Execution Time: 0.312 ms
```

## Deep-cursor pagination: depth-vs-latency (transactions, 1,000,000 rows, index present)

The cursor `WHERE` clause is `created_at < :cursor OR (created_at = :cursor AND id < :cursor_id)` — a disjunctive condition. PostgreSQL cannot translate this into a single sargable index-range boundary against a plain two-column btree index: it pushes `created_at <= :cursor` in as an `Index Cond`, then applies the rest as a `Filter`, walking every index entry in the matching range until it finds 26 that pass.

| Cursor depth (rows past page 1) | Time with index | Comparable "before" baseline (same query, no index) |
|---|---|---|
| 250 (≈page 10 at 25/page) | 1.8ms | ~146-205ms (flat, regardless of depth) |
| 2,500 (≈page 100) | 11.9ms | same |
| 25,000 (≈page 1,000) | 75.0ms | same |
| 250,000 (≈page 10,000) | **429.6ms (worse)** | same |
| 500,000 (halfway through the table) | **2,621ms (worse)** | 146.3ms |

**Crossover point: roughly 75,000-100,000 rows deep.** Below that, the index is a clear win even for cursor pagination (not just page 1); beyond it, `PostgreSQL`'s cost estimator chooses the index anyway (it does not know in advance how many rows the `Filter` will discard) even though it performs worse than the sequential-scan-and-sort plan it replaces.

**This is a genuine, measured limitation, not a hypothetical one — reported here plainly rather than omitted.** Fixing it would require restructuring the cursor `WHERE` clause into a row-value comparison (`(created_at, id) < (:cursor, :cursor_id)`) and confirming PostgreSQL can push that into an efficient index-range scan (a follow-up spike showed even that form did not reliably produce a sargable `Index Cond` for this query shape in this PostgreSQL version) — that is a pagination-logic change, explicitly out of PR14B's scope.

**Why this is accepted rather than blocking:** this system's confirmed business scale is an Equipment Pool fleet — "low hundreds of devices, thousands of transactions per year" (`docs/audits/04-consolidated-implementation-plan.md`), not the hospital-wide asset register this stress test targets. Reaching a cursor 75,000+ rows deep requires several thousand consecutive "next page" clicks in one session — not a realistically reachable UI access pattern at this system's actual scale, even over many years of accumulated history. The dramatic, unconditional win (page one, by far the dominant real access pattern) is squarely within realistic usage; the regression is confined to a depth this system's real users will not reach.

## Success-criteria verification

- **PostgreSQL query plans use the new indexes where expected** — verified structurally, not assumed: `backend/tests/test_postgres_integration.py::test_migration_0011_planner_uses_the_new_index_for_first_page_equipment_query` seeds 3,000 rows, runs `EXPLAIN` on the literal first-page query, and asserts the plan contains `Index Scan` and no `Sort` node.
- **No API contract change** — no route, request/response schema, or status code touched.
- **Cursor pagination returns identical results** — `test_migration_0011_cursor_pagination_returns_identical_complete_result_set` paginates through 120 seeded rows and asserts every row is visited exactly once, in the same order a single unpaginated query returns them.
- **`COUNT(*)` behavior unchanged** — `test_migration_0011_count_star_behavior_is_unchanged` asserts `total` from `equipment_crud.search()` is still an exact, soft-delete-aware `COUNT(*)`, not an index-derived estimate.
- **Historical upgrades succeed / fresh installs succeed / downgrades and re-upgrades succeed** — `test_migration_0011_fresh_database_upgrade_to_head_converges_on_expected_schema`, `test_migration_0011_historical_0010_upgrade_downgrade_re_upgrade_round_trip` (both paths verified locally against real PostgreSQL 16 before these tests were written, then captured as regression tests).
- **Indexes match the real `ORDER BY`, descending** — `test_migration_0011_indexes_are_descending_matching_the_orm_query_order` inspects `pg_indexes.indexdef` directly (SQLAlchemy's generic reflection does not reliably report index column direction).

## Benchmark summary: page-selection vs. `COUNT(*)` vs. total latency

For query 1 (`GET /equipment`, no filters), `app.crud.equipment.search()` issues the `COUNT(*)` and the page-selection query as two separate statements in the same request:

| Component | Before | After |
|---|---|---|
| Page-selection query (the one this migration indexes) | 55.5ms | 0.31ms |
| `COUNT(*)` query (Finding 5.2, unchanged, out of scope) | 46.9ms | 46.9ms (unchanged) |
| Total (both queries, sequential) | ~102ms | ~47ms |

The `COUNT(*)` query remains the dominant cost after this migration — expected and accepted, per the standing instruction that `COUNT(*)` optimization is explicitly out of PR14B's scope (Backend Audit 5.2 was independently deprioritized to P2/Medium for this system's confirmed scale).
