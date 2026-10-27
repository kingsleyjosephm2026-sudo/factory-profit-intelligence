import { BarsChart, TimeChart } from "../components/charts";
import { Async, Badge, Card, DataTable, ExportButton, Note, PageHeader, type Col } from "../components/ui";
import { fmtMoney, fmtNum, fmtPct } from "../format";
import { useApi } from "../hooks";
import { useApp } from "../state";

const n0: Col["render"] = (v) => fmtNum(v);
const p2: Col["render"] = (v) => fmtPct(v);

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return <div className="card p-4"><div className="text-xs font-medium text-slate-600">{label}</div><div className="mt-1 text-2xl font-semibold tabular-nums">{value}</div>{hint && <div className="text-xs text-slate-500">{hint}</div>}</div>;
}

export function ProductionPage() {
  const res = useApi("/api/analytics/production");
  const group = (rows: any[], key: string, label: string) => (
    <DataTable rows={rows} initialSort={{ key: "units", desc: true }} cols={[{ key, label }, { key: "units", label: "Units", align: "right", render: n0 }, { key: "good", label: "Good", align: "right", render: n0 },
      { key: "defective", label: "Defective", align: "right", render: n0 }, { key: "target_attainment_pct", label: "Target %", align: "right", render: p2 }, { key: "efficiency_pct", label: "Efficiency %", align: "right", render: p2 }]} />
  );
  return (
    <>
      <PageHeader title="Production Analytics" subtitle="Output, target attainment and efficiency by machine, product, shift and line." actions={<ExportButton path="/api/export/production" label="Export records CSV" />} />
      <Async res={res} empty={(d) => !d.totals}>
        {(d) => (
          <>
            <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
              <Stat label="Units produced" value={fmtNum(d.totals.units)} /><Stat label="Good units" value={fmtNum(d.totals.good)} />
              <Stat label="Target attainment" value={fmtPct(d.totals.target_attainment_pct)} /><Stat label="Output efficiency" value={fmtPct(d.totals.efficiency_pct)} hint="Units vs ideal rate x period" />
            </div>
            <Card className="mt-4" title="Output versus target over time"><TimeChart data={d.trend} series={[{ key: "units", label: "Produced", kind: "bar", digits: 0 }, { key: "target", label: "Target", color: "#d97706", digits: 0 }]} /></Card>
            <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-2">
              <Card title="By machine">{group(d.by_machine, "machine_code", "Machine")}</Card><Card title="By production line">{group(d.by_line, "line_name", "Line")}</Card>
              <Card title="By product">{group(d.by_product, "product_sku", "Product")}</Card><Card title="By shift">{group(d.by_shift, "shift", "Shift")}</Card>
            </div>
          </>
        )}
      </Async>
    </>
  );
}

export function DowntimePage() {
  const { config } = useApp();
  const cur = config?.currency ?? "INR";
  const res = useApi("/api/analytics/downtime");
  return (
    <>
      <PageHeader title="Machine Downtime" subtitle="Planned and unplanned downtime are separated: only unplanned stops are treated as loss." actions={<ExportButton path="/api/export/downtime" label="Export events CSV" />} />
      <Async res={res} empty={(d) => d.totals.unplanned_events + d.totals.planned_events === 0}>
        {(d) => (
          <>
            <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
              <Stat label="Unplanned downtime" value={`${fmtNum(d.totals.unplanned_minutes)} min`} hint={`${d.totals.unplanned_events} events`} />
              <Stat label="Planned downtime" value={`${fmtNum(d.totals.planned_minutes)} min`} hint={`${d.totals.planned_events} events (not counted as loss)`} />
              <Stat label="Estimated margin impact" value={fmtMoney(d.totals.impact, cur, true)} hint="Estimated, margin based" />
              <Stat label="Worst machine" value={d.by_machine[0]?.machine_code ?? "n/a"} hint={d.by_machine[0] ? `${fmtPct(d.by_machine[0].unplanned_pct)} of scheduled time` : undefined} />
            </div>
            <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-2">
              <Card title="Downtime trend" subtitle="Minutes"><TimeChart data={d.trend} series={[{ key: "unpl_down", label: "Unplanned", kind: "area", color: "#dc2626", digits: 0 }, { key: "planned_down", label: "Planned", kind: "area", color: "#94a3b8", digits: 0 }]} /></Card>
              <Card title="Unplanned downtime by reason (Pareto)" subtitle="Minutes by reason code"><BarsChart data={d.reasons_unplanned} labelKey="reason_code" series={[{ key: "minutes", label: "Minutes", digits: 0 }]} /></Card>
            </div>
            <Card className="mt-4" title="By machine" subtitle="MTBF and MTTR are shown only for machines with at least 3 unplanned events">
              <DataTable rows={d.by_machine} initialSort={{ key: "impact", desc: true }} cols={[{ key: "machine_code", label: "Machine" }, { key: "unplanned_minutes", label: "Unplanned min", align: "right", render: n0 }, { key: "planned_minutes", label: "Planned min", align: "right", render: n0 },
                { key: "unplanned_pct", label: "Unplanned %", align: "right", render: p2 }, { key: "events", label: "Events", align: "right" }, { key: "mtbf_hours", label: "MTBF (h)", align: "right", render: (v) => fmtNum(v, 1) }, { key: "mttr_minutes", label: "MTTR (min)", align: "right", render: (v) => fmtNum(v, 1) },
                { key: "lost_units", label: "Lost units", align: "right", render: n0 }, { key: "impact", label: "Margin impact", align: "right", render: (v) => fmtMoney(v, cur, true) }]} />
            </Card>
            <Card className="mt-4" title="Planned downtime by reason"><BarsChart data={d.reasons_planned} labelKey="reason_code" series={[{ key: "minutes", label: "Minutes", color: "#94a3b8", digits: 0 }]} height={200} /></Card>
            <div className="mt-3"><Note>{d.note}</Note></div>
          </>
        )}
      </Async>
    </>
  );
}

export function QualityPage() {
  const { config } = useApp();
  const cur = config?.currency ?? "INR";
  const res = useApi("/api/analytics/quality");
  const grp = (rows: any[], key: string, label: string) => (
    <DataTable rows={rows} initialSort={{ key: "defect_rate_pct", desc: true }} cols={[{ key, label }, { key: "units", label: "Units", align: "right", render: n0 }, { key: "defective", label: "Defective", align: "right", render: n0 },
      { key: "defect_rate_pct", label: "Defect %", align: "right", render: p2 }, { key: "loss_quality", label: "Quality cost", align: "right", render: (v) => fmtMoney(v, cur, true) }]} />
  );
  return (
    <>
      <PageHeader title="Quality and Defects" subtitle="Defect rate = defective units / units produced. Quality cost is the wasted input cost of scrapped units, not a full lost sale." actions={<ExportButton path="/api/export/quality" label="Export defects CSV" />} />
      <Async res={res} empty={(d) => !d.totals}>
        {(d) => (
          <>
            <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
              <Stat label="Defect rate" value={fmtPct(d.totals.defect_rate_pct)} /><Stat label="Defective units" value={fmtNum(d.totals.defective)} />
              <Stat label="First-pass yield" value={fmtPct(d.first_pass_yield_pct)} hint="No rework data: equals yield" /><Stat label="Estimated quality cost" value={fmtMoney(d.totals.loss_quality, cur, true)} />
            </div>
            <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-2">
              <Card title="Defect rate trend" subtitle="% of units"><TimeChart data={d.trend} series={[{ key: "defect_rate_pct", label: "Defect rate %", color: "#7c3aed" }]} /></Card>
              <Card title="Defect categories" subtitle="Units"><BarsChart data={d.categories} labelKey="category" series={[{ key: "units", label: "Defective units", digits: 0 }]} /></Card>
              <Card title="By shift">{grp(d.by_shift, "shift", "Shift")}</Card><Card title="By production line">{grp(d.by_line, "line_name", "Line")}</Card>
              <Card title="By machine">{grp(d.by_machine, "machine_code", "Machine")}</Card><Card title="By product">{grp(d.by_product, "product_sku", "Product")}</Card>
            </div>
            <div className="mt-3"><Note>{d.note}</Note></div>
          </>
        )}
      </Async>
    </>
  );
}

export function EnergyPage() {
  const { config } = useApp();
  const cur = config?.currency ?? "INR";
  const res = useApi("/api/analytics/energy");
  return (
    <>
      <PageHeader title="Energy Analytics" subtitle="Consumption, cost and intensity. Abnormal intervals are measured against each machine and product's own median kWh per unit." actions={<ExportButton path="/api/export/energy" label="Export energy CSV" />} />
      <Async res={res} empty={(d) => !d.totals}>
        {(d) => (
          <>
            <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
              <Stat label="Energy used" value={`${fmtNum(d.totals.kwh)} kWh`} /><Stat label="Energy cost" value={fmtMoney(d.totals.energy_cost, cur, true)} />
              <Stat label="Energy per good unit" value={`${fmtNum(d.totals.kwh_per_good_unit, 3)} kWh`} /><Stat label="Excess energy cost (est.)" value={fmtMoney(d.totals.loss_energy, cur, true)} hint={`${d.abnormal.flagged_records} abnormal intervals`} />
            </div>
            <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-2">
              <Card title="Consumption trend" subtitle="kWh"><TimeChart data={d.trend} series={[{ key: "kwh", label: "kWh", kind: "area", digits: 0 }]} /></Card>
              <Card title="Energy intensity trend" subtitle="kWh per good unit"><TimeChart data={d.trend} series={[{ key: "kwh_per_good_unit", label: "kWh / good unit", color: "#d97706", digits: 3 }]} /></Card>
              <Card title="Energy cost by line"><BarsChart data={d.by_line} labelKey="line_name" currency={cur} series={[{ key: "energy_cost", label: "Energy cost", money: true }]} /></Card>
              <Card title="Energy per good unit by machine"><BarsChart data={d.by_machine} labelKey="machine_code" series={[{ key: "kwh_per_good_unit", label: "kWh / good unit", digits: 3 }]} /></Card>
            </div>
            <Card className="mt-4" title="Abnormal consumption indicators" subtitle={d.abnormal.definition}>
              <DataTable rows={d.abnormal.top} cols={[{ key: "period_start", label: "Interval", render: (v) => String(v).replace("T", " ").slice(0, 16) }, { key: "machine_code", label: "Machine" }, { key: "product_sku", label: "Product" },
                { key: "kwh_per_unit", label: "kWh/unit", align: "right", render: (v) => fmtNum(v, 3) }, { key: "base_kwh_unit", label: "Baseline", align: "right", render: (v) => fmtNum(v, 3) }, { key: "ratio", label: "Ratio", align: "right", render: (v) => `${fmtNum(v, 2)}x` },
                { key: "loss_energy", label: "Excess cost", align: "right", render: (v) => fmtMoney(v, cur) }]} />
            </Card>
          </>
        )}
      </Async>
    </>
  );
}

export function InventoryPage() {
  const { config } = useApp();
  const cur = config?.currency ?? "INR";
  const res = useApi("/api/analytics/inventory");
  return (
    <>
      <PageHeader title="Inventory Analysis" subtitle="Latest stock position, reorder-point breaches, stockout days, slow-moving stock and carrying cost for the selected period." actions={<ExportButton path="/api/export/inventory" label="Export inventory CSV" />} />
      <Async res={res} empty={(d) => !d.items.length}>
        {(d) => (
          <>
            <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
              <Stat label="Reorder-point breaches" value={String(d.summary.breaches)} hint={`of ${d.summary.items} items`} /><Stat label="Stockout days" value={String(d.summary.stockout_days)} />
              <Stat label="Slow-moving items" value={String(d.summary.slow_moving)} hint="More than 90 days of cover" /><Stat label="Carrying cost (est.)" value={fmtMoney(d.summary.carrying_cost, cur, true)} hint={`${fmtMoney(d.summary.avoidable_carrying_cost, cur, true)} avoidable`} />
            </div>
            <Card className="mt-4" title="Items" subtitle="Position as of the last snapshot in the selected period">
              <DataTable rows={d.items} initialSort={{ key: "days_of_cover", desc: false }} cols={[{ key: "item_code", label: "Item" }, { key: "item_name", label: "Name" }, { key: "line_name", label: "Line" },
                { key: "quantity_on_hand", label: "On hand", align: "right", render: n0 }, { key: "reorder_point", label: "Reorder pt", align: "right", render: n0 }, { key: "days_of_cover", label: "Days cover", align: "right", render: (v) => fmtNum(v, 1) },
                { key: "below_reorder", label: "Status", render: (_v, r) => r.below_reorder ? <Badge kind="red">Below reorder point</Badge> : r.slow_moving ? <Badge kind="amber">Slow moving</Badge> : <Badge kind="green">OK</Badge> },
                { key: "stockout_days", label: "Stockout days", align: "right" }, { key: "stock_value", label: "Stock value", align: "right", render: (v) => fmtMoney(v, cur, true) }, { key: "carrying_cost", label: "Carrying cost", align: "right", render: (v) => fmtMoney(v, cur, true) }]} />
            </Card>
            <div className="mt-3"><Note>Inventory carrying cost is allocated to production lines only (never to machines, products or shifts). Snapshots exist for the demo history; the live simulation does not change inventory.</Note></div>
          </>
        )}
      </Async>
    </>
  );
}
