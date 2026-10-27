# Data dictionary (SIMULATED DEMO DATA)

Timestamps are factory-local and timezone-naive. Shifts: A 06:00-14:00, B 14:00-22:00, C 22:00-06:00. Currency INR (configurable).

**Fictional company:** 1 factory, 3 lines (A injection moulding, B CNC machining, C assembly & test), 10 machines, 8 products in 6 categories, 90 days, 2,700 shift-level production records, ~5.3k downtime events, ~9k defect-category rows, 2,700 energy rows, 630 inventory snapshots (7 items), ~470 maintenance events.

| Table | Field | Meaning |
|---|---|---|
| machine | rated_units_per_hour, power_kw, crew_size | nameplate rate, electrical load, operators |
| product | unit_price, std_material_cost, std_conversion_cost, speed_factor | contribution margin = price - material - conversion; speed relative to machine rating |
| production_record | period_start, period_minutes, shift | interval (480 for history, 15 for simulation) |
| | planned_downtime_min / unplanned_downtime_min | changeover, scheduled maintenance, calibration / stops. Equals the sum of downtime events in the interval |
| | units_produced, defective_units, target_units | output, scrapped units, target (ideal x 85%) |
| | material_cost, labor_hours, labor_cost | actual material spend (std x (1+waste)), crew hours, hours x 230 |
| | source | demo, import or simulation |
| downtime_event | start_ts, duration_min, planned, reason_code | reason codes: MECH_BEARING, MECH_BELT, ELEC_SENSOR, ELEC_POWER, MAT_SHORTAGE, JAM, OPER_ABSENCE, QUALITY_HOLD, TOOL_WEAR (unplanned); CHANGEOVER, PM_SCHEDULED, CALIBRATION (planned) |
| quality_record | defect_category, defective_units | splits a record's defects; sums to defective_units |
| energy_record | kwh, tariff | consumption and currency/kWh (A 6.8, B 8.4 peak, C 5.6) |
| inventory_snapshot | quantity_on_hand, reorder_point, avg_daily_usage, unit_cost | daily stock; usage derived from line output |
| maintenance_event | category, duration_min, cost | Preventive, Corrective - Mechanical/Electrical |
| recommendation | rule_id, entity_key, status, notes, active ... | persisted rule output and user actions |
| savings_initiative | periods, values, evidence_status, evidence_json | server-computed evidence status |
| data_import_log | file_sha256, status, rows_* , errors_json | import history and duplicate-file guard |

## Coherence rules
good + defective = units; planned + unplanned <= period; units = ideal rate x run time x performance; energy follows run and idle time; material follows units; inventory usage follows line output. Tests assert these.

## Deliberately planted patterns (so analytics find something)
M-B2 bearing failures worsening over 90 days · M-A3 electrical faults plus an energy drift in the last ~25 days · Line C night-shift defect growth · M-B4 extra material waste · Shift C lower performance · Alloy Billet supplier late (stockouts) · PCB below reorder point at the end · Packaging cartons slow-moving.

## Import CSV formats
`sample_data/*_template.csv` list the exact columns. Production: machine_code, product_sku, period_start, period_minutes, planned_downtime_min, unplanned_downtime_min, units_produced, defective_units, target_units, material_cost, labor_hours, labor_cost, [shift]. Downtime: machine_code, start_ts, duration_min, planned, reason_code. Energy: machine_code, period_start, kwh, tariff. Inventory: line_code, item_code, item_name, snapshot_date, quantity_on_hand, reorder_point, unit_cost, avg_daily_usage.
