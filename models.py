"""SQLAlchemy models.

Every important column carries a `comment=` that is used to generate DATA_DICTIONARY.md
(scripts/gen_docs.py), so the dictionary can not drift from the schema.

Conventions
-----------
* Timestamps are *plant-local, timezone-naive* datetimes (the factory's `timezone` column
  documents the zone). Production/energy records are hourly (period_start inclusive).
* Money columns are Numeric(14,2) in the configured currency (default INR).
* `source` is one of: history (generated demo history), live_sim (live demo simulator),
  import (user CSV import).
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

MONEY = Numeric(14, 2)
QTY = Numeric(14, 3)


class Base(DeclarativeBase):
    pass


def _now() -> datetime:
    return datetime.utcnow()


class Factory(Base):
    __tablename__ = "factories"
    __table_args__ = {"comment": "A manufacturing site."}
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, comment="Short unique site code, e.g. PLANT-01")
    name: Mapped[str] = mapped_column(String(120), comment="Display name of the site")
    location: Mapped[str | None] = mapped_column(String(120), comment="Free-text location (fictional in the demo)")
    timezone: Mapped[str] = mapped_column(String(48), default="Asia/Kolkata", comment="IANA zone in which naive timestamps are expressed")
    currency: Mapped[str] = mapped_column(String(3), default="INR", comment="ISO 4217 currency for all money columns")
    lines: Mapped[list["ProductionLine"]] = relationship(back_populates="factory", cascade="all, delete-orphan")


class ProductionLine(Base):
    __tablename__ = "production_lines"
    __table_args__ = (UniqueConstraint("factory_id", "code"), {"comment": "A production line inside a factory."})
    id: Mapped[int] = mapped_column(primary_key=True)
    factory_id: Mapped[int] = mapped_column(ForeignKey("factories.id", ondelete="CASCADE"), index=True)
    code: Mapped[str] = mapped_column(String(32), comment="Line code, e.g. L1")
    name: Mapped[str] = mapped_column(String(120), comment="Line display name")
    factory: Mapped[Factory] = relationship(back_populates="lines")
    machines: Mapped[list["Machine"]] = relationship(back_populates="line", cascade="all, delete-orphan")


class Machine(Base):
    __tablename__ = "machines"
    __table_args__ = (
        CheckConstraint("rated_kw >= 0 AND idle_kw >= 0", name="ck_machine_power_nonneg"),
        CheckConstraint("speed_factor > 0", name="ck_machine_speed_pos"),
        {"comment": "A machine / work centre on a production line."},
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    line_id: Mapped[int] = mapped_column(ForeignKey("production_lines.id", ondelete="CASCADE"), index=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, comment="Unique machine code, e.g. CNC-101")
    name: Mapped[str] = mapped_column(String(120), comment="Machine display name")
    machine_type: Mapped[str] = mapped_column(String(48), comment="Machine family (CNC, Press, Welder, Assembly, Packaging, Lathe)")
    rated_kw: Mapped[float] = mapped_column(Numeric(9, 2), default=0, comment="Typical running electrical load in kW (reference only; baselines are fitted from data)")
    idle_kw: Mapped[float] = mapped_column(Numeric(9, 2), default=0, comment="Typical idle/standby load in kW (reference only)")
    speed_factor: Mapped[float] = mapped_column(Numeric(6, 3), default=1, comment="Machine speed relative to the product's base cycle time")
    crew_size: Mapped[int] = mapped_column(Integer, default=1, comment="Operators assigned per scheduled hour")
    line: Mapped[ProductionLine] = relationship(back_populates="machines")


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint("selling_price >= 0 AND bom_kg_per_unit >= 0 AND material_cost_per_kg >= 0", name="ck_product_money_nonneg"),
        CheckConstraint("target_defect_rate_pct >= 0 AND target_defect_rate_pct <= 100", name="ck_product_target_defect_range"),
        {"comment": "A finished product / SKU with its standard cost data."},
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    sku: Mapped[str] = mapped_column(String(32), unique=True, comment="Unique product code")
    name: Mapped[str] = mapped_column(String(120), comment="Product name")
    category: Mapped[str] = mapped_column(String(64), index=True, comment="Product category (e.g. Housings, Brackets, Assemblies)")
    primary_line_code: Mapped[str | None] = mapped_column(String(32), comment="Line on which the product is mainly made (informational)")
    selling_price: Mapped[Decimal] = mapped_column(MONEY, comment="Average net selling price per unit (currency)")
    material_code: Mapped[str] = mapped_column(String(48), comment="Raw-material inventory item consumed by this product")
    bom_kg_per_unit: Mapped[float] = mapped_column(Numeric(9, 4), comment="Standard material mass per unit (kg), incl. blended components")
    material_cost_per_kg: Mapped[Decimal] = mapped_column(MONEY, comment="Standard material cost per kg (currency)")
    std_conversion_cost: Mapped[Decimal] = mapped_column(MONEY, comment="Standard variable conversion cost per unit excluding material (consumables, energy, variable labour)")
    rework_cost: Mapped[Decimal] = mapped_column(MONEY, comment="Average cost to rework one defective unit (currency)")
    target_defect_rate_pct: Mapped[float] = mapped_column(Numeric(6, 3), default=1.5, comment="Accepted defect rate (% of units); defects above this are treated as avoidable")
    base_cycle_sec: Mapped[float] = mapped_column(Numeric(9, 2), comment="Ideal cycle time per unit in seconds at speed_factor = 1")


class ProductionRecord(Base):
    __tablename__ = "production_records"
    __table_args__ = (
        UniqueConstraint("machine_id", "period_start", name="uq_production_machine_period"),
        CheckConstraint("units_produced >= 0 AND good_units >= 0 AND defective_units >= 0", name="ck_prod_units_nonneg"),
        CheckConstraint("good_units + defective_units = units_produced", name="ck_prod_units_balance"),
        CheckConstraint("planned_minutes >= 0 AND planned_downtime_minutes >= 0 AND unplanned_downtime_minutes >= 0 AND run_minutes >= 0", name="ck_prod_minutes_nonneg"),
        CheckConstraint("period_end > period_start", name="ck_prod_period_order"),
        CheckConstraint("shift IN ('A','B','C')", name="ck_prod_shift"),
        Index("ix_prod_period", "period_start"),
        {"comment": "Hourly production result of one machine (one row per machine per hour)."},
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    machine_id: Mapped[int] = mapped_column(ForeignKey("machines.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    period_start: Mapped[datetime] = mapped_column(DateTime, comment="Start of the hour (plant-local, inclusive)")
    period_end: Mapped[datetime] = mapped_column(DateTime, comment="End of the hour (exclusive)")
    shift: Mapped[str] = mapped_column(String(1), comment="Shift: A 06:00-14:00, B 14:00-22:00, C 22:00-06:00")
    planned_minutes: Mapped[int] = mapped_column(Integer, comment="Scheduled production minutes in the period")
    planned_downtime_minutes: Mapped[int] = mapped_column(Integer, default=0, comment="Planned stoppage (maintenance, calibration, changeover) minutes inside the period")
    unplanned_downtime_minutes: Mapped[int] = mapped_column(Integer, default=0, comment="Unplanned stoppage (breakdown, starvation, quality hold) minutes inside the period")
    run_minutes: Mapped[int] = mapped_column(Integer, comment="Minutes the machine was producing = planned - planned downtime - unplanned downtime")
    ideal_cycle_time_sec: Mapped[float] = mapped_column(Numeric(9, 2), comment="Ideal seconds per unit for this machine/product")
    target_units: Mapped[float] = mapped_column(Numeric(12, 2), comment="Production target for the period (accounts for planned downtime, not unplanned)")
    units_produced: Mapped[int] = mapped_column(Integer, comment="Total units produced (good + defective)")
    good_units: Mapped[int] = mapped_column(Integer, comment="Units passing first-pass inspection")
    defective_units: Mapped[int] = mapped_column(Integer, comment="Units failing first-pass inspection (scrapped or sent to rework)")
    material_kg_used: Mapped[float] = mapped_column(QTY, comment="Actual raw material consumed (kg)")
    labor_hours: Mapped[float] = mapped_column(Numeric(9, 2), comment="Paid labour hours attributed to the period")
    labor_cost: Mapped[Decimal] = mapped_column(MONEY, comment="Labour cost for the period (currency)")
    source: Mapped[str] = mapped_column(String(16), default="history", index=True, comment="history | live_sim | import")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    machine: Mapped[Machine] = relationship()
    product: Mapped[Product] = relationship()


class DowntimeEvent(Base):
    __tablename__ = "downtime_events"
    __table_args__ = (
        UniqueConstraint("machine_id", "start_ts", "reason_code", name="uq_downtime_event"),
        CheckConstraint("end_ts > start_ts", name="ck_downtime_order"),
        CheckConstraint("duration_minutes > 0", name="ck_downtime_duration_pos"),
        Index("ix_downtime_start", "start_ts"),
        {"comment": "A machine stoppage with start/end timestamps and a reason code."},
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    machine_id: Mapped[int] = mapped_column(ForeignKey("machines.id", ondelete="CASCADE"), index=True)
    start_ts: Mapped[datetime] = mapped_column(DateTime, comment="Stoppage start")
    end_ts: Mapped[datetime] = mapped_column(DateTime, comment="Stoppage end")
    duration_minutes: Mapped[float] = mapped_column(Numeric(9, 2), comment="Duration in minutes (= end - start)")
    planned: Mapped[bool] = mapped_column(Boolean, default=False, comment="True for planned stops (maintenance, changeover); False for unplanned")
    reason_code: Mapped[str] = mapped_column(String(24), index=True, comment="Downtime reason code, e.g. MECH-HYD (see reference table)")
    reason_category: Mapped[str] = mapped_column(String(32), comment="Reason family: Mechanical, Electrical, Tooling, Material, Quality, Operator, Utility, Maintenance, Changeover")
    description: Mapped[str | None] = mapped_column(String(200), comment="Free text description")
    source: Mapped[str] = mapped_column(String(16), default="history", index=True, comment="history | live_sim | import")
    machine: Mapped[Machine] = relationship()


class QualityRecord(Base):
    __tablename__ = "quality_records"
    __table_args__ = (
        UniqueConstraint("production_record_id", "defect_category", name="uq_quality_prod_category"),
        CheckConstraint("defect_units > 0 AND scrapped_units >= 0 AND reworked_units >= 0", name="ck_quality_nonneg"),
        CheckConstraint("scrapped_units + reworked_units = defect_units", name="ck_quality_balance"),
        {"comment": "Defects of one production record split by defect category and disposition."},
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    production_record_id: Mapped[int] = mapped_column(ForeignKey("production_records.id", ondelete="CASCADE"), index=True)
    defect_category: Mapped[str] = mapped_column(String(48), index=True, comment="Defect category (Dimensional, Surface, Weld, Assembly fit, Material flaw, Packaging damage)")
    defect_units: Mapped[int] = mapped_column(Integer, comment="Defective units in this category (>0)")
    scrapped_units: Mapped[int] = mapped_column(Integer, comment="Of which scrapped (material and conversion lost)")
    reworked_units: Mapped[int] = mapped_column(Integer, comment="Of which reworked and recovered (rework cost incurred)")
    source: Mapped[str] = mapped_column(String(16), default="history", comment="history | live_sim | import")
    production_record: Mapped[ProductionRecord] = relationship()


class EnergyRecord(Base):
    __tablename__ = "energy_records"
    __table_args__ = (
        UniqueConstraint("machine_id", "period_start", name="uq_energy_machine_period"),
        CheckConstraint("kwh >= 0 AND tariff_per_kwh >= 0", name="ck_energy_nonneg"),
        Index("ix_energy_period", "period_start"),
        {"comment": "Metered electrical energy of one machine for one hour."},
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    machine_id: Mapped[int] = mapped_column(ForeignKey("machines.id", ondelete="CASCADE"), index=True)
    period_start: Mapped[datetime] = mapped_column(DateTime, comment="Start of the hour")
    kwh: Mapped[float] = mapped_column(Numeric(12, 3), comment="Energy consumed in kWh")
    tariff_per_kwh: Mapped[Decimal] = mapped_column(Numeric(8, 3), comment="Applicable tariff (currency per kWh; time-of-day dependent)")
    energy_cost: Mapped[Decimal] = mapped_column(MONEY, comment="kwh x tariff_per_kwh (currency)")
    source: Mapped[str] = mapped_column(String(16), default="history", index=True, comment="history | live_sim | import")
    machine: Mapped[Machine] = relationship()


class InventorySnapshot(Base):
    __tablename__ = "inventory_snapshots"
    __table_args__ = (
        UniqueConstraint("snapshot_date", "item_code", name="uq_inventory_day_item"),
        CheckConstraint("qty_on_hand >= 0 AND unit_cost >= 0 AND reorder_point >= 0 AND max_level >= 0", name="ck_inventory_nonneg"),
        CheckConstraint("item_type IN ('raw_material','finished_good')", name="ck_inventory_type"),
        {"comment": "End-of-day stock level of one inventory item."},
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_date: Mapped[date] = mapped_column(Date, index=True, comment="Stock date (end of day)")
    item_code: Mapped[str] = mapped_column(String(48), index=True, comment="Material code or product SKU")
    item_name: Mapped[str] = mapped_column(String(120), comment="Item description")
    item_type: Mapped[str] = mapped_column(String(16), comment="raw_material | finished_good")
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"), comment="Product for finished goods")
    qty_on_hand: Mapped[float] = mapped_column(QTY, comment="Quantity on hand at end of day (kg for raw material, units for finished goods)")
    unit: Mapped[str] = mapped_column(String(8), comment="kg or units")
    unit_cost: Mapped[Decimal] = mapped_column(MONEY, comment="Valuation cost per unit")
    reorder_point: Mapped[float] = mapped_column(QTY, comment="Stock level at/below which replenishment should be triggered")
    max_level: Mapped[float] = mapped_column(QTY, comment="Target maximum stock level; stock above it is treated as excess")
    daily_usage: Mapped[float] = mapped_column(QTY, default=0, comment="Quantity consumed/shipped on this day")
    source: Mapped[str] = mapped_column(String(16), default="history", comment="history | live_sim | import")


class MaintenanceEvent(Base):
    __tablename__ = "maintenance_events"
    __table_args__ = (
        CheckConstraint("category IN ('preventive','corrective','predictive','calibration','overhaul')", name="ck_maint_category"),
        CheckConstraint("duration_minutes >= 0 AND cost >= 0", name="ck_maint_nonneg"),
        {"comment": "A maintenance work order."},
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    machine_id: Mapped[int] = mapped_column(ForeignKey("machines.id", ondelete="CASCADE"), index=True)
    downtime_event_id: Mapped[int | None] = mapped_column(ForeignKey("downtime_events.id", ondelete="SET NULL"), comment="Related stoppage, if any")
    event_ts: Mapped[datetime] = mapped_column(DateTime, index=True, comment="When the work started")
    category: Mapped[str] = mapped_column(String(16), comment="preventive | corrective | predictive | calibration | overhaul")
    description: Mapped[str] = mapped_column(String(200), comment="Work description")
    duration_minutes: Mapped[float] = mapped_column(Numeric(9, 2), comment="Work duration in minutes")
    cost: Mapped[Decimal] = mapped_column(MONEY, comment="Parts + labour cost of the work order (currency)")
    planned: Mapped[bool] = mapped_column(Boolean, default=True, comment="Planned (scheduled) work vs reactive")
    source: Mapped[str] = mapped_column(String(16), default="history", comment="history | live_sim | import")


class Recommendation(Base):
    __tablename__ = "recommendations"
    __table_args__ = (
        UniqueConstraint("dedupe_key", name="uq_reco_dedupe"),
        CheckConstraint("status IN ('open','in_progress','resolved','dismissed')", name="ck_reco_status"),
        CheckConstraint("severity IN ('critical','high','medium','low')", name="ck_reco_severity"),
        {"comment": "A rule-generated recommendation with evidence and a user-managed status."},
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    dedupe_key: Mapped[str] = mapped_column(String(160), comment="rule_code:entity - one live recommendation per rule and entity")
    rule_code: Mapped[str] = mapped_column(String(40), index=True, comment="Rule that produced it")
    title: Mapped[str] = mapped_column(String(200), comment="Short action-oriented title")
    evidence: Mapped[str] = mapped_column(Text, comment="Numbers that triggered the rule")
    entity_type: Mapped[str] = mapped_column(String(24), comment="machine | line | product | item | shift")
    entity_label: Mapped[str] = mapped_column(String(80), comment="Affected machine/line/product/item")
    trigger_metric: Mapped[str] = mapped_column(String(80), comment="Metric that crossed the rule threshold")
    trigger_value: Mapped[float | None] = mapped_column(Numeric(16, 4), comment="Observed metric value")
    threshold_value: Mapped[float | None] = mapped_column(Numeric(16, 4), comment="Threshold it was compared with")
    severity: Mapped[str] = mapped_column(String(10), comment="critical | high | medium | low")
    recommended_action: Mapped[str] = mapped_column(Text, comment="Suggested next step")
    estimated_opportunity: Mapped[Decimal | None] = mapped_column(MONEY, comment="Conservative estimated savings opportunity over opportunity_period_days (null when not defensible)")
    opportunity_period_days: Mapped[int | None] = mapped_column(Integer, comment="Length of the evaluation window the opportunity refers to")
    opportunity_basis: Mapped[str | None] = mapped_column(Text, comment="How the opportunity was computed, or why it is not quantified")
    evidence_strength: Mapped[str] = mapped_column(String(12), comment="strong | moderate | limited (based on sample size and effect size)")
    calculation_method: Mapped[str] = mapped_column(Text, comment="Plain-language method")
    generated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, comment="First generated")
    last_evaluated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, comment="Last time the rule was evaluated for this entity")
    as_of: Mapped[datetime | None] = mapped_column(DateTime, comment="Data timestamp the evaluation window ended at")
    condition_active: Mapped[bool] = mapped_column(Boolean, default=True, comment="Whether the rule still triggers in the latest evaluation")
    status: Mapped[str] = mapped_column(String(12), default="open", index=True, comment="open | in_progress | resolved | dismissed")
    status_updated_at: Mapped[datetime | None] = mapped_column(DateTime)
    notes: Mapped[list["RecommendationNote"]] = relationship(back_populates="recommendation", cascade="all, delete-orphan", order_by="RecommendationNote.created_at")


class RecommendationNote(Base):
    __tablename__ = "recommendation_notes"
    __table_args__ = {"comment": "User notes attached to a recommendation (also records status changes)."}
    id: Mapped[int] = mapped_column(primary_key=True)
    recommendation_id: Mapped[int] = mapped_column(ForeignKey("recommendations.id", ondelete="CASCADE"), index=True)
    note: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    recommendation: Mapped[Recommendation] = relationship(back_populates="notes")


class SavingsInitiative(Base):
    __tablename__ = "savings_initiatives"
    __table_args__ = (
        CheckConstraint("evidence_status IN ('opportunity_identified','forecast','estimated','verified')", name="ck_savings_status"),
        CheckConstraint("measurement_mode IN ('system','manual')", name="ck_savings_mode"),
        {"comment": "A corrective initiative whose savings are tracked and verified against a baseline."},
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    problem_category: Mapped[str] = mapped_column(String(24), comment="downtime | quality | energy | material | inventory")
    scope_type: Mapped[str] = mapped_column(String(12), default="machine", comment="machine | line | plant")
    scope_code: Mapped[str | None] = mapped_column(String(32), comment="Machine or line code the initiative applies to (null = plant)")
    control_scope_code: Mapped[str | None] = mapped_column(String(32), comment="Optional comparable machine/line without the intervention (counterfactual)")
    recommendation_id: Mapped[int | None] = mapped_column(ForeignKey("recommendations.id", ondelete="SET NULL"))
    measurement_mode: Mapped[str] = mapped_column(String(8), default="system", comment="system = baseline/post values measured from the dataset; manual = typed by the user (can never be 'verified')")
    baseline_start: Mapped[date | None] = mapped_column(Date)
    baseline_end: Mapped[date | None] = mapped_column(Date)
    baseline_metric: Mapped[str] = mapped_column(String(48), comment="Metric name, e.g. unplanned_downtime_minutes")
    baseline_value: Mapped[float | None] = mapped_column(Numeric(18, 4), comment="Baseline metric total over the baseline period")
    baseline_volume: Mapped[float | None] = mapped_column(Numeric(18, 4), comment="Normaliser over baseline (planned hours / run hours / good units)")
    intervention_date: Mapped[date | None] = mapped_column(Date)
    post_start: Mapped[date | None] = mapped_column(Date)
    post_end: Mapped[date | None] = mapped_column(Date)
    post_metric: Mapped[str | None] = mapped_column(String(48))
    post_value: Mapped[float | None] = mapped_column(Numeric(18, 4), comment="Post-intervention metric total over the post period")
    post_volume: Mapped[float | None] = mapped_column(Numeric(18, 4))
    normalization: Mapped[str] = mapped_column(String(16), default="per_planned_hour", comment="none | per_planned_hour | per_run_hour | per_good_unit")
    unit_value: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), comment="Currency value of one unit of the metric (e.g. contribution margin per downtime minute)")
    implementation_cost: Mapped[Decimal | None] = mapped_column(MONEY, comment="One-off cost of the intervention (subtracted for net savings)")
    expected_savings: Mapped[Decimal | None] = mapped_column(MONEY, comment="Forecast savings per measurement period before the intervention")
    calculated_savings: Mapped[Decimal | None] = mapped_column(MONEY, comment="System calculated savings over the post period (gross)")
    net_savings: Mapped[Decimal | None] = mapped_column(MONEY, comment="calculated_savings - implementation_cost")
    assumptions: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    confirm_no_confounders: Mapped[bool] = mapped_column(Boolean, default=False, comment="User attests no other process change happened in the window")
    confirm_finance_review: Mapped[bool] = mapped_column(Boolean, default=False, comment="User attests finance reviewed the unit value")
    evidence_status: Mapped[str] = mapped_column(String(24), default="opportunity_identified", comment="opportunity_identified | forecast | estimated | verified - computed by the server, never set directly")
    evidence_report: Mapped[dict | None] = mapped_column(JSON, comment="Checks that passed/failed, test statistics, caveats")
    is_example: Mapped[bool] = mapped_column(Boolean, default=False, comment="True for the clearly labelled simulated example")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class DataImportLog(Base):
    __tablename__ = "data_import_logs"
    __table_args__ = (
        CheckConstraint("status IN ('success','partial','failed','duplicate_file','preview')", name="ck_import_status"),
        {"comment": "Audit trail of CSV imports and validations."},
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    dataset: Mapped[str] = mapped_column(String(24), index=True, comment="machines | products | production | downtime | quality | energy | inventory | maintenance | demo")
    filename: Mapped[str] = mapped_column(String(200))
    file_sha256: Mapped[str | None] = mapped_column(String(64), index=True, comment="Hash used to block accidental re-imports of the same file")
    status: Mapped[str] = mapped_column(String(16))
    rows_total: Mapped[int] = mapped_column(Integer, default=0)
    rows_accepted: Mapped[int] = mapped_column(Integer, default=0)
    rows_rejected: Mapped[int] = mapped_column(Integer, default=0)
    rows_duplicate: Mapped[int] = mapped_column(Integer, default=0, comment="Rows skipped because the natural key already exists")
    errors: Mapped[list | None] = mapped_column(JSON, comment="First rejected-row messages (capped)")
    message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, index=True)


class AppSetting(Base):
    __tablename__ = "app_settings"
    __table_args__ = {"comment": "Runtime-editable settings (loss-model assumptions)."}
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict | list | float | int | str | None] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class SimulationState(Base):
    __tablename__ = "simulation_state"
    __table_args__ = (CheckConstraint("id = 1", name="ck_sim_singleton"), {"comment": "Single-row state of the live demo simulator."})
    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    running: Mapped[bool] = mapped_column(Boolean, default=False)
    sim_clock: Mapped[datetime | None] = mapped_column(DateTime, comment="Simulated plant time of the next hour to generate")
    history_end: Mapped[datetime | None] = mapped_column(DateTime, comment="Timestamp where generated history ended (reset target)")
    tick_count: Mapped[int] = mapped_column(Integer, default=0)
    seed: Mapped[int] = mapped_column(Integer, default=0)
    last_tick_at: Mapped[datetime | None] = mapped_column(DateTime, comment="Wall-clock time of the last tick (UTC)")
    carry: Mapped[dict | None] = mapped_column(JSON, comment="Per-machine carry-over state (open downtime, hours since PM, inventory pipeline)")
    data_version: Mapped[int] = mapped_column(Integer, default=0, comment="Incremented on every data write; used for cache invalidation")


# Downtime reason catalogue (reference data; also exported to the UI)
DOWNTIME_REASONS: dict[str, dict] = {
    "MECH-BRG": {"label": "Bearing / spindle failure", "category": "Mechanical", "planned": False},
    "MECH-HYD": {"label": "Hydraulic leak / pressure loss", "category": "Mechanical", "planned": False},
    "ELEC-SNS": {"label": "Sensor / PLC fault", "category": "Electrical", "planned": False},
    "ELEC-DRV": {"label": "Drive / VFD trip", "category": "Electrical", "planned": False},
    "TOOL-BRK": {"label": "Tool or die breakage", "category": "Tooling", "planned": False},
    "MAT-SHT": {"label": "Material shortage / starvation", "category": "Material", "planned": False},
    "QC-HOLD": {"label": "Quality hold / line stop", "category": "Quality", "planned": False},
    "OPR-ERR": {"label": "Operator error / setup issue", "category": "Operator", "planned": False},
    "UTL-PWR": {"label": "Utility / power dip", "category": "Utility", "planned": False},
    "PM-SCH": {"label": "Scheduled preventive maintenance", "category": "Maintenance", "planned": True},
    "CAL": {"label": "Calibration", "category": "Maintenance", "planned": True},
    "CHG-OVR": {"label": "Product changeover", "category": "Changeover", "planned": True},
}

DEFECT_CATEGORIES = ["Dimensional", "Surface finish", "Weld defect", "Assembly fit", "Material flaw", "Packaging damage"]
