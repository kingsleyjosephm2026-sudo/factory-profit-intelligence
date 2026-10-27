import { useState } from "react";
import { BarsChart, TimeChart } from "../components/charts";
import { Async, Badge, Card, DataTable, ExportButton, MetricDefinition, Note, PageHeader, type Col } from "../components/ui";
import { fmtMoney, fmtNum, fmtPct } from "../format";
import { useApi } from "../hooks";
import { useApp } from "../state";

type By = "machine" | "line" | "product" | "shift" | "date";
const LABEL_KEY: Record<By, string> = { machine: "machine_code", line: "line_name", product: "product_sku", shift: "shift", date: "bucket" };
const CATS = [["downtime", "Downtime impact"], ["quality", "Quality-related cost"], ["energy", "Excess energy"], ["material", "Material waste"], ["inventory", "Inventory carrying cost"]] as const;

export default function ProfitLeakage() {
  const { config } = useApp();
  const cur = config?.currency ?? "INR";
  const [by, setBy] = useState<By>("machine");
  const [cat, setCat] = useState<string>("downtime");
  const summary = useApi("/api/loss/summary");
  const breakdown = useApi("/api/loss/breakdown", { by, grain: "week" });
  const drill = useApi("/api/loss/drilldown", { category: cat, page_size: 25 });
  const m = (v: number) => fmtMoney(v, cur, true);
  const moneyCol = (key: string, label: string): Col => ({ key, label, align: "right", render: (v) => (v === undefined || v === null ? "n/a" : m(v)) });
  return (
    <>
      <PageHeader title="Profit Leakage Explorer" subtitle="Ranks the largest sources of operational loss and separates what was observed from what is plausibly avoidable."
        actions={<ExportButton path="/api/export/loss" params={{ by }} label="Export ranking CSV" />} />
      <Async res={summary}>
        {(d) => (
          <>
            <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
              <div className="card p-4"><div className="flex justify-between text-xs font-medium text-slate-600">Observed cost <MetricDefinition docKey="loss_downtime" /></div><div className="mt-1 text-2xl font-semibold">{m(d.totals.observed)}</div><div className="text-xs text-slate-500">Modelled cost attributed to the five categories</div></div>
              <div className="card p-4"><div className="flex justify-between text-xs font-medium text-slate-600">Estimated avoidable cost <MetricDefinition docKey="avoidable" /></div><div className="mt-1 text-2xl font-semibold">{m(d.totals.avoidable)}</div><div className="text-xs text-slate-500">The part above explicit benchmarks</div></div>
              <div className="card p-4"><div className="flex justify-between text-xs font-medium text-slate-600">Potential future savings <MetricDefinition docKey="potential" /></div><div className="mt-1 text-2xl font-semibold">{m(d.totals.potential)}</div><div className="text-xs text-slate-500">Avoidable x {config?.assumptions.realization_factor ?? 0.5} realization. Unverified.</div></div>
            </div>
            <div className="mt-3"><Note tone="warn">{d.note} {!d.inventory_applicable && "Inventory carrying cost is not allocated to machine, product or shift filters, so it is excluded while one is active."}</Note></div>
            <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-2">
              <Card title="Ranked loss categories"><DataTable rows={d.categories} initialSort={{ key: "observed", desc: true }} caption="Loss categories ranked by observed cost" cols={[
                { key: "label", label: "Category", render: (v, r) => <button className="text-brand-600 underline" onClick={() => setCat(r.category)}>{v}</button> },
                moneyCol("observed", "Observed"), moneyCol("avoidable", "Avoidable"), moneyCol("potential", "Potential savings")]} /></Card>
              <Card title="Observed, avoidable and potential"><BarsChart data={d.categories} labelKey="label" currency={cur} series={[{ key: "observed", label: "Observed", money: true }, { key: "avoidable", label: "Avoidable", money: true }, { key: "potential", label: "Potential savings", money: true }]} /></Card>
            </div>
          </>
        )}
      </Async>
      <Card className="mt-4" title="Ranking and comparison" actions={
        <div className="flex gap-1" role="tablist">{(["machine", "line", "product", "shift", "date"] as By[]).map((b) => (
          <button key={b} role="tab" aria-selected={by === b} className={`btn px-2 py-1 ${by === b ? "btn-primary" : ""}`} onClick={() => setBy(b)}>{b === "date" ? "Trend (weekly)" : b[0].toUpperCase() + b.slice(1)}</button>))}</div>}>
        <Async res={breakdown} empty={(d) => !d.rows.length}>
          {(d) => (
            <>
              {by === "date" && <div className="mb-3"><TimeChart data={d.rows} currency={cur} stacked series={[{ key: "loss_downtime", label: "Downtime", kind: "area", money: true }, { key: "loss_quality", label: "Quality", kind: "area", money: true, color: "#7c3aed" }, { key: "loss_material", label: "Material", kind: "area", money: true, color: "#059669" }, { key: "loss_energy", label: "Energy", kind: "area", money: true, color: "#d97706" }]} /></div>}
              <DataTable rows={d.rows} pageSize={10} initialSort={by === "date" ? undefined : { key: "observed_loss", desc: true }} cols={[
                { key: LABEL_KEY[by], label: by === "date" ? "Week of" : by },
                { key: "defect_rate_pct", label: "Defect %", align: "right", render: (v) => fmtPct(v) },
                { key: "unplanned_downtime_pct", label: "Unplanned DT %", align: "right", render: (v) => fmtPct(v) },
                moneyCol("loss_downtime", "Downtime"), moneyCol("loss_quality", "Quality"), moneyCol("loss_energy", "Energy"), moneyCol("loss_material", "Material"),
                ...(by === "line" ? [moneyCol("inventory_observed", "Inventory")] : []),
                moneyCol("observed_loss", "Observed"), moneyCol("avoidable_cost", "Avoidable"), moneyCol("potential_savings", "Potential")]} />
            </>
          )}
        </Async>
      </Card>
      <Card className="mt-4" title="Drill-down to underlying records" subtitle="The records behind each category, largest first (first 25)" actions={
        <select className="input" aria-label="Category to drill into" value={cat} onChange={(e) => setCat(e.target.value)}>{CATS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>}>
        <Async res={drill} empty={(d) => !d.items.length}>
          {(d) => (
            <>
              <div className="mb-3 rounded-lg bg-slate-50 p-3 text-xs text-slate-700">
                <div className="mb-1 flex items-center gap-2"><strong>{d.explanation.label}</strong><Badge kind="amber">{d.explanation.type}</Badge></div>
                <div><strong>Formula:</strong> <span className="font-mono">{d.explanation.formula}</span></div>
                <div><strong>Assumptions:</strong> {d.explanation.assumptions}</div>
                <div><strong>Limitations:</strong> {d.explanation.limitations}</div>
              </div>
              <div className="text-xs text-slate-500">{fmtNum(d.total)} records</div>
              <DataTable pageSize={10} rows={d.items} cols={Object.keys(d.items[0]).map((k) => ({ key: k, label: k.replace(/_/g, " "), align: typeof d.items[0][k] === "number" ? "right" as const : undefined, render: (v: any) => typeof v === "number" ? fmtNum(v, Math.abs(v) < 100 ? 2 : 0) : String(v ?? "n/a").replace("T", " ") }))} />
            </>
          )}
        </Async>
      </Card>
    </>
  );
}
