"""Metric documentation served by /api/metrics and shown in the UI. type: measured | calculated | estimated."""

METRICS: dict[str, dict] = {
    "total_units": dict(
        label="Total production", type="measured", unit="units",
        formula="sum(units_produced)", inputs=["production_record.units_produced"],
        assumptions="Counts every unit that left the machine, good or defective.",
        limitations="Does not distinguish rework passes; each interval is counted once.",
    ),
    "good_units": dict(
        label="Good units", type="calculated", unit="units",
        formula="sum(units_produced - defective_units)", inputs=["units_produced", "defective_units"],
        assumptions="Defective units are scrapped (no rework data is captured).", limitations="First-pass yield equals yield without rework tracking.",
    ),
    "defect_rate": dict(
        label="Defect rate", type="calculated", unit="%",
        formula="defective_units / units_produced x 100", inputs=["defective_units", "units_produced"],
        assumptions="Zero production gives no rate (shown as n/a), never 0%.", limitations="Aggregates are volume-weighted, not averages of interval rates.",
    ),
    "first_pass_yield": dict(
        label="First-pass yield", type="calculated", unit="%",
        formula="good_units / units_produced x 100", inputs=["units_produced", "defective_units"],
        assumptions="No rework captured, so FPY = 100% - defect rate.", limitations="Becomes distinct from yield only once rework data is available.",
    ),
    "unplanned_downtime": dict(
        label="Unplanned downtime", type="measured", unit="minutes",
        formula="sum(unplanned_downtime_min)", inputs=["production_record.unplanned_downtime_min", "downtime_event"],
        assumptions="Planned downtime (changeover, scheduled maintenance, calibration) is reported separately and never counted as loss.",
        limitations="Event-level views (MTBF, MTTR, reasons) ignore the product filter because events are not product-specific.",
    ),
    "mtbf": dict(
        label="Mean time between failures", type="calculated", unit="hours",
        formula="run hours / number of unplanned events", inputs=["run_minutes", "downtime_event"],
        assumptions="Each unplanned event is a failure.", limitations="Needs at least 3 events per machine to be meaningful.",
    ),
    "mttr": dict(
        label="Mean time to repair", type="calculated", unit="minutes",
        formula="sum(unplanned event minutes) / number of unplanned events", inputs=["downtime_event.duration_min"],
        assumptions="Event duration approximates repair time.", limitations="Includes waiting time for parts or staff.",
    ),
    "target_attainment": dict(
        label="Target attainment", type="calculated", unit="%",
        formula="units_produced / target_units x 100", inputs=["units_produced", "target_units"],
        assumptions="Target = ideal rate x available minutes x target efficiency (85% by default).", limitations="Targets are supplied with the data, not derived from demand.",
    ),
    "energy_cost": dict(
        label="Energy cost", type="calculated", unit="currency",
        formula="sum(kwh x tariff)", inputs=["energy_record.kwh", "energy_record.tariff"],
        assumptions="Time-of-day tariff per shift as supplied.", limitations="Demand charges and power-factor penalties are not modelled.",
    ),
    "kwh_per_good_unit": dict(
        label="Energy per good unit", type="calculated", unit="kWh/unit",
        formula="sum(kwh) / sum(good_units)", inputs=["kwh", "good_units"],
        assumptions="All energy of an interval is attributed to its units.", limitations="Idle energy is included, so it rises with downtime.",
    ),
    "loss_downtime": dict(
        label="Downtime impact", type="estimated", unit="currency",
        formula="(unplanned_min/60 x ideal_units_per_hour) x contribution_margin_per_unit x unrecoverable_share",
        inputs=["unplanned_downtime_min", "machine rate", "product speed", "price", "std material", "std conversion"],
        assumptions="Margin (not revenue) is lost, and only the unrecoverable share (default 70%) because some output is recovered by overtime or stock.",
        limitations="Ignores demand constraints and contractual penalties. Revenue loss is deliberately NOT added to avoid double counting.",
    ),
    "loss_quality": dict(
        label="Quality-related cost", type="estimated", unit="currency",
        formula="defective_units x (std_material + std_conversion) x (1 - salvage_rate)",
        inputs=["defective_units", "std costs", "salvage rate"],
        assumptions="A defective unit wastes the inputs spent on it; it is not treated as a full lost sale. 10% salvage by default.",
        limitations="Excludes warranty, rework labour and customer-complaint costs (not captured).",
    ),
    "loss_energy": dict(
        label="Excess energy", type="estimated", unit="currency",
        formula="max(0, kwh - baseline_kwh_per_unit x units x (1 + tolerance)) x tariff",
        inputs=["kwh", "units", "tariff", "per machine+product median kWh/unit"],
        assumptions="Baseline is the median kWh/unit of that machine and product over all loaded history; 5% tolerance absorbs normal variation.",
        limitations="If history already contains a drift the baseline is inflated and loss is understated (conservative).",
    ),
    "loss_material": dict(
        label="Material waste", type="estimated", unit="currency",
        formula="max(0, material_cost - units x std_material x (1 + allowance))", inputs=["material_cost", "units", "std_material"],
        assumptions="Only consumption beyond standard (1% allowance) is waste; the input cost of defective units is counted under quality, not here.",
        limitations="Actual material cost per interval must be supplied; otherwise this category is zero.",
    ),
    "loss_inventory": dict(
        label="Inventory carrying cost", type="estimated", unit="currency",
        formula="sum over snapshots of quantity x unit_cost x annual_rate / 365", inputs=["inventory_snapshot"],
        assumptions="18% annual carrying rate. Avoidable = carrying cost of stock above 45 days of usage.",
        limitations="Allocated to lines only; it does not appear in machine, product or shift rankings.",
    ),
    "avoidable": dict(
        label="Estimated avoidable cost", type="estimated", unit="currency",
        formula="Observed cost above an explicit benchmark (downtime 5% of time, defects 2%, energy 60% of excess, material 50% of excess, inventory above 45 days cover)",
        inputs=["observed loss", "benchmarks"], assumptions="Benchmarks are configurable (FPI_* settings).",
        limitations="Benchmarks are illustrative and should be replaced with company targets.",
    ),
    "potential": dict(
        label="Potential future savings", type="estimated", unit="currency",
        formula="avoidable cost x realization factor (50% by default)", inputs=["avoidable"],
        assumptions="Only half of the avoidable cost is assumed capturable.", limitations="A planning figure, not a forecast; it is unverified until a savings initiative proves it.",
    ),
    "oee_efficiency": dict(
        label="Output efficiency", type="calculated", unit="%",
        formula="units_produced / (ideal_rate x period_hours) x 100", inputs=["units_produced", "ideal rate", "period"],
        assumptions="Combines availability and performance; quality is reported separately.", limitations="Not a certified OEE figure.",
    ),
}
