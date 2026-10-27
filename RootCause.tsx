import { useState } from "react";
import { Async, Card, DataTable, Note, PageHeader, type Col } from "../components/ui";
import { BarsChart } from "../components/charts";
import { fmtNum } from "../format";
import { useApi } from "../hooks";
import { Link } from "react-router-dom";

const Limit = ({ reason }: { reason: string }) => <Note tone="warn">Insufficient data: {reason}</Note>;
const idx: Col["render"] = (v) => (v === null || v === undefined ? "n/a" : <span className={v > 1.2 ? "font-semibold text-red-700" : v < 0.85 ? "text-green-700" : ""}>{fmtNum(v, 2)}</span>);

export default function RootCause() {
  const res = useApi("/api/rootcause");
  const [dim, setDim] = useState<"machine" | "shift" | "line" | "product">("machine");
  return (
    <>
      <PageHeader title="Root Cause Explorer" subtitle="Exploratory analysis of the selected window. These are observed associations, never proof of cause." />
      <Async res={res}>
        {(d) => (
          <>
            <Note tone="warn">{d.note}</Note>
            <Card className="mt-4" title="Correlation analysis" subtitle="Pearson correlation across machine-days. 'Within machine' removes differences between machines.">
              {!d.correlations.available ? <Limit reason={d.correlations.reason} /> : (
                <DataTable rows={d.correlations.pairs} pageSize={8} initialSort={{ key: "r", desc: true }} cols={[
                  { key: "a", label: "Metric A", render: (v) => String(v).replace(/_/g, " ") }, { key: "b", label: "Metric B", render: (v) => String(v).replace(/_/g, " ") },
                  { key: "r", label: "r", align: "right", render: (v) => fmtNum(v, 2) }, { key: "r_within_machine", label: "r within machine", align: "right", render: (v) => fmtNum(v, 2) },
                  { key: "n", label: "n", align: "right" }, { key: "strength", label: "Strength" }, { key: "exceeds_noise", label: "Above noise?", render: (v) => (v ? "Yes" : "No") }]} />
              )}
            </Card>
            <Card className="mt-4" title="Group comparison" subtitle="Index = group value / overall (1.00 = average). Red cells are 20%+ worse than average."
              actions={<select className="input" aria-label="Group by" value={dim} onChange={(e) => setDim(e.target.value as typeof dim)}><option value="machine">Machine</option><option value="shift">Shift</option><option value="line">Line</option><option value="product">Product</option></select>}>
              {d.groups ? (
                <>
                  <DataTable rows={d.groups[dim]} pageSize={12} cols={[{ key: Object.keys(d.groups[dim][0] ?? { k: 1 })[0], label: dim },
                    { key: "units", label: "Units", align: "right", render: (v) => fmtNum(v) }, { key: "defect_rate_pct", label: "Defect %", align: "right", render: (v) => fmtNum(v, 2) }, { key: "defect_index", label: "Defect idx", align: "right", render: idx },
                    { key: "unplanned_downtime_pct", label: "Unplanned DT %", align: "right", render: (v) => fmtNum(v, 2) }, { key: "downtime_index", label: "Downtime idx", align: "right", render: idx },
                    { key: "kwh_per_good_unit", label: "kWh/unit", align: "right", render: (v) => fmtNum(v, 3) }, { key: "energy_index", label: "Energy idx", align: "right", render: idx }]} />
                  <p className="mt-2 text-xs text-slate-500">{d.groups.note}</p>
                </>
              ) : <Limit reason="no records" />}
            </Card>
            <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-2">
              <Card title="Trend comparison: first half vs second half" subtitle="Change in unplanned downtime % per machine">
                {!d.trends.available ? <Limit reason={d.trends.reason} /> : (
                  <>
                    <BarsChart data={d.trends.machines} labelKey="machine_code" series={[{ key: "unplanned_downtime_pct_change", label: "Change in unplanned downtime (pts)", color: "#dc2626" }]} />
                    <p className="mt-1 text-xs text-slate-500">Window split at {d.trends.split_date}. {d.trends.note}</p>
                  </>
                )}
              </Card>
              <Card title="Downtime reasons by machine" subtitle="Top machine and reason combinations (minutes)">
                {!d.reasons.available ? <Limit reason={d.reasons.reason} /> : (
                  <DataTable rows={d.reasons.top_combinations} pageSize={8} cols={[{ key: "machine_code", label: "Machine" }, { key: "reason_code", label: "Reason" }, { key: "duration_min", label: "Minutes", align: "right", render: (v) => fmtNum(v, 0) }]} />
                )}
              </Card>
            </div>
            <Card className="mt-4" title="Outliers" subtitle="Machine-days that are unusual for that machine itself (modified z-score)">
              {!d.outliers.available ? <Limit reason={d.outliers.reason} /> : (
                <>
                  <p className="mb-2 text-xs text-slate-500">{d.outliers.method}. {d.outliers.count} found.</p>
                  <DataTable rows={d.outliers.items} pageSize={8} cols={[{ key: "machine_code", label: "Machine" }, { key: "date", label: "Date" }, { key: "metric", label: "Metric", render: (v) => String(v).replace(/_/g, " ") },
                    { key: "value", label: "Value", align: "right", render: (v) => fmtNum(v, 2) }, { key: "expected", label: "Typical", align: "right", render: (v) => fmtNum(v, 2) }, { key: "robust_z", label: "z", align: "right", render: (v) => fmtNum(v, 1) },
                    { key: "records_link", label: "Records", sortable: false, render: (_v, r) => <Link className="text-brand-600 underline" to={`/data?dataset=production&machine=${r.machine_code}&date=${r.date}`}>Open records</Link> }]} />
                </>
              )}
            </Card>
          </>
        )}
      </Async>
    </>
  );
}
