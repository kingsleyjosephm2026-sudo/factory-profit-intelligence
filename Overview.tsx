import { useState } from "react";
import { BarsChart, TimeChart } from "../components/charts";
import { Async, Card, Kpi, Note, PageHeader } from "../components/ui";
import { useApi } from "../hooks";
import { useApp } from "../state";

export default function Overview() {
  const { config } = useApp();
  const [grain, setGrain] = useState<"day" | "week" | "month">("day");
  const summary = useApi("/api/dashboard/summary");
  const charts = useApi("/api/dashboard/charts", { grain });
  const cur = config?.currency ?? "INR";
  return (
    <>
      <PageHeader title="Executive Overview" subtitle="Where the factory is losing money, and how much of it is plausibly recoverable. All figures respond to the filters above."
        actions={<><label className="label mb-0" htmlFor="grain">Trend granularity</label>
          <select id="grain" className="input" value={grain} onChange={(e) => setGrain(e.target.value as typeof grain)}><option value="day">Daily</option><option value="week">Weekly</option><option value="month">Monthly</option></select></>} />
      <Async res={summary} empty={(d) => d.records === 0}>
        {(d) => (
          <>
            <p className="mb-2 text-xs text-slate-500">Compared with {d.previous_period.date_from} to {d.previous_period.date_to} (previous period of equal length).</p>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">{d.cards.map((c: any) => <Kpi key={c.key} card={c} currency={cur} />)}</div>
          </>
        )}
      </Async>
      <div className="mt-4"><Note>Estimated operational loss is a modelled estimate (see the definition on each card). It is not recoverable profit: the Profit Leakage page separates observed cost, estimated avoidable cost and potential future savings.</Note></div>
      <Async res={charts} empty={(d) => !d.production_vs_target.length}>
        {(d) => (
          <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-2">
            <Card title="Production versus target" subtitle="Units"><TimeChart data={d.production_vs_target} series={[{ key: "units", label: "Produced", kind: "bar" }, { key: "target", label: "Target", kind: "line", color: "#d97706", digits: 0 }]} /></Card>
            <Card title="Operational loss by category" subtitle="Observed vs estimated avoidable vs potential savings"><BarsChart data={d.loss_by_category} labelKey="label" currency={cur}
              series={[{ key: "observed", label: "Observed", money: true }, { key: "avoidable", label: "Avoidable", money: true }, { key: "potential", label: "Potential savings", money: true }]} /></Card>
            <Card title="Unplanned downtime trend" subtitle="Minutes (planned downtime shown separately)"><TimeChart data={d.downtime_trend} series={[{ key: "unpl_down", label: "Unplanned", kind: "area", color: "#dc2626", digits: 0 }, { key: "planned_down", label: "Planned", kind: "area", color: "#94a3b8", digits: 0 }]} /></Card>
            <Card title="Defect rate trend" subtitle="% of units produced"><TimeChart data={d.defect_trend} series={[{ key: "defect_rate_pct", label: "Defect rate %", color: "#7c3aed" }]} /></Card>
            <Card title="Energy consumption trend" subtitle="kWh and cost"><TimeChart data={d.energy_trend} series={[{ key: "kwh", label: "kWh", kind: "area", digits: 0 }]} /></Card>
            <Card title="Loss by production line" subtitle="Observed cost; inventory carrying cost included at line level"><BarsChart data={d.loss_by_line} labelKey="line_name" currency={cur} stacked
              series={[{ key: "loss_downtime", label: "Downtime", money: true }, { key: "loss_quality", label: "Quality", money: true }, { key: "loss_energy", label: "Energy", money: true }, { key: "loss_material", label: "Material", money: true }, { key: "inventory_observed", label: "Inventory", money: true }]} /></Card>
            <Card title="Top five machines by estimated loss" className="xl:col-span-2"><BarsChart data={d.top_machines} labelKey="machine_code" currency={cur} stacked horizontal height={260}
              series={[{ key: "loss_downtime", label: "Downtime", money: true }, { key: "loss_quality", label: "Quality", money: true }, { key: "loss_energy", label: "Energy", money: true }, { key: "loss_material", label: "Material", money: true }]} /></Card>
          </div>
        )}
      </Async>
    </>
  );
}
