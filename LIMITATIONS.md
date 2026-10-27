# Limitations and simplifications

- All numbers come from a fictional, simulated dataset unless you import your own. No real machinery or sensor is connected; "live" mode is a controlled simulation that writes simulated rows.
- No authentication, authorisation or multi-tenancy (deliberately omitted from the local demo rather than faked).
- Loss figures are model estimates with configurable, illustrative assumptions (70% unrecoverable downtime, 10% scrap salvage, benchmarks, 50% realization). They are not accounting figures and not forecasts.
- "Verified" savings means a statistical comparison with a baseline that passed all checks. It is not a controlled experiment and does not prove causation.
- Reference data (lines, machines, products) cannot yet be edited or imported through the UI.
- Quality: no rework tracking, so first-pass yield equals yield. Imported defects are categorised "Unclassified".
- Inventory is line-level only and static during the live simulation; stockouts are inferred from zero-quantity snapshots.
- Event-level downtime views ignore the product filter. Downtime events are not linked to production records by foreign key; consistency is by construction and checked in tests.
- Energy baselines use the median of all loaded history, which understates loss if history already contains a drift.
- Financial arithmetic: record level uses float64; published aggregates are rounded with Decimal.
- The whole filtered window is loaded into pandas per request (fine for ~10^4 rows, not tuned for millions).
- PostgreSQL and Docker paths are untested here. Simulation uses a single in-process worker (one API process).
- Excel export is a plain data dump (no formatting). Single currency. Light theme only.
