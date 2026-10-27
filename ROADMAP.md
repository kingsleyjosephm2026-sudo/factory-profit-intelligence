# Roadmap: from simulated demo to real factory data

1. **Reference-data management**: UI/CSV import for lines, machines, products, standard costs; shift calendars.
2. **Authentication and roles** (read-only analyst, plant manager, admin) and audit log.
3. **Real data ingestion**: map the client's MES/ERP/historian exports to the four import formats; scheduled file drops, then a documented connector (OPC UA / MQTT / SQL view) writing with `source='sensor'` through the existing validation path. Run in parallel with the manual process and reconcile totals.
4. **Calibrate the model with the client**: real contribution margins, benchmark targets, tariffs, recoverable-share of lost output, scrap and rework costs; replace the illustrative defaults.
5. **Richer quality and maintenance data**: rework, defect-to-event linkage, work orders, spare-part cost.
6. **Savings verification upgrades**: control lines/machines, seasonality adjustment, interrupted time-series, sign-off workflow.
7. **Operations**: PostgreSQL migrations in CI, background jobs, alerting, performance work (pre-aggregation), full accessibility audit.

## Suggested first pilot
Find one small discrete-manufacturing plant (10-30 machines) willing to share **authorised, anonymised** exports for 3-6 months: production counts by machine and shift, downtime logs with reason codes, scrap counts, and energy meter readings, plus standard costs. Ask the plant manager to name their top three suspected losses beforehand. Success = the tool independently surfaces at least one of them with evidence, one recommendation is acted on, and the Savings Verification module measures the result against a baseline. Agree data-handling terms in writing first, and report only what the data shows.
