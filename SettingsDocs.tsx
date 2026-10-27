import { Fragment } from "react";
import { Async, Badge, Card, DataTable, Note, PageHeader } from "../components/ui";
import { fmtDateTime } from "../format";
import { useApi } from "../hooks";
import { useApp } from "../state";

const LIMITS = [
  "All data is SIMULATED unless you import your own. Nothing here is connected to real machinery or sensors.",
  "There is no authentication or authorisation. Run it locally; do not expose it to the internet.",
  "Financial figures are modelled estimates built on documented, configurable assumptions. They are not accounting figures.",
  "Savings marked 'verified' passed statistical and coverage checks against a baseline. This is not a controlled experiment and does not prove causation.",
  "Inventory is allocated to production lines only, and the live simulation does not change inventory.",
  "Event-level downtime views (reasons, MTBF, MTTR) ignore the product filter.",
  "No rework data is captured, so first-pass yield equals overall yield.",
];

export default function SettingsDocs() {
  const { config } = useApp();
  const metrics = useApi("/api/metrics", {}, { filtered: false });
  return (
    <>
      <PageHeader title="Settings & Documentation" subtitle="Assumptions behind the loss model, metric definitions and known limitations." />
      <Note tone="warn">{config?.warning ?? "Demo build."}</Note>
      <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-2">
        <Card title="Environment" subtitle="Read-only. Change values with FPI_* environment variables (see .env.example).">
          <dl className="grid grid-cols-2 gap-2 text-sm"><dt className="text-slate-500">Data label</dt><dd>{config?.data_label}</dd><dt className="text-slate-500">Currency</dt><dd>{config?.currency}</dd><dt className="text-slate-500">Database</dt><dd>{config?.database}</dd>
            <dt className="text-slate-500">Data range</dt><dd>{config?.data_from} to {config?.data_to}</dd><dt className="text-slate-500">Production records</dt><dd>{config?.production_records.toLocaleString()}</dd><dt className="text-slate-500">Last successful import</dt><dd>{config?.last_import_at ? fmtDateTime(config.last_import_at) : "none"}</dd></dl>
        </Card>
        <Card title="Loss-model assumptions" subtitle="Conservative defaults. Replace with company figures.">
          <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-sm">{Object.entries(config?.assumptions ?? {}).map(([k, v]) => <Fragment key={k}><dt className="text-slate-500">{k.replace(/_/g, " ")}</dt><dd className="tabular-nums">{v}</dd></Fragment>)}</dl>
        </Card>
      </div>
      <Card className="mt-4" title="Known limitations"><ul className="list-disc space-y-1 pl-5 text-sm text-slate-700">{LIMITS.map((l) => <li key={l}>{l}</li>)}</ul></Card>
      <Card className="mt-4" title="Metric definitions" subtitle="Formula, inputs, assumptions and limitations. Type shows whether a value is measured, calculated or estimated.">
        <Async res={metrics}>{(d) => <DataTable pageSize={20} rows={Object.entries(d).map(([k, v]: [string, any]) => ({ key: k, ...v }))} cols={[
          { key: "label", label: "Metric" }, { key: "type", label: "Type", render: (v) => <Badge kind={v === "measured" ? "green" : v === "calculated" ? "blue" : "amber"}>{v}</Badge> }, { key: "unit", label: "Unit" },
          { key: "formula", label: "Formula", render: (v) => <span className="whitespace-normal font-mono text-xs">{v}</span> }, { key: "assumptions", label: "Assumptions", render: (v) => <span className="whitespace-normal text-xs">{v}</span> },
          { key: "limitations", label: "Limitations", render: (v) => <span className="whitespace-normal text-xs">{v}</span> }]} />}</Async>
      </Card>
      <Card className="mt-4" title="API documentation"><p className="text-sm text-slate-700">Interactive OpenAPI docs are served by the backend at <code>/docs</code> (Swagger UI) and <code>/redoc</code>. With the default setup: <a className="text-brand-600 underline" href="http://localhost:8000/docs" target="_blank" rel="noreferrer">http://localhost:8000/docs</a>.</p></Card>
    </>
  );
}
