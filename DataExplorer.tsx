import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { ApiError, downloadUrl, send, upload } from "../api";
import { Async, Badge, Card, DataTable, ErrorBox, ExportButton, Note, PageHeader, ServerTable, type Col } from "../components/ui";
import { fmtDateTime, fmtNum } from "../format";
import { useApi } from "../hooks";
import { useApp } from "../state";

const ts = (v: any) => String(v ?? "").replace("T", " ").slice(0, 16);
const TABS: Record<string, { label: string; path: string; cols: Col[] }> = {
  production: { label: "Production", path: "/api/production", cols: [{ key: "period_start", label: "Interval", render: ts }, { key: "machine_code", label: "Machine" }, { key: "product_sku", label: "Product" }, { key: "shift", label: "Shift" },
    { key: "units", label: "Units", align: "right" }, { key: "defective", label: "Defective", align: "right" }, { key: "target", label: "Target", align: "right" }, { key: "planned_down", label: "Planned DT", align: "right" }, { key: "unpl_down", label: "Unplanned DT", align: "right" }, { key: "source", label: "Source" }] },
  downtime: { label: "Downtime", path: "/api/downtime", cols: [{ key: "start_ts", label: "Start", render: ts }, { key: "machine_code", label: "Machine" }, { key: "duration_min", label: "Minutes", align: "right" }, { key: "planned", label: "Planned", render: (v) => (v ? "Yes" : "No") }, { key: "reason_code", label: "Reason" }, { key: "source", label: "Source" }] },
  quality: { label: "Quality", path: "/api/quality", cols: [{ key: "period_start", label: "Interval", render: ts }, { key: "machine_code", label: "Machine" }, { key: "shift", label: "Shift" }, { key: "defect_category", label: "Defect category" }, { key: "defective_units", label: "Units", align: "right" }] },
  energy: { label: "Energy", path: "/api/energy", cols: [{ key: "period_start", label: "Interval", render: ts }, { key: "machine_code", label: "Machine" }, { key: "kwh", label: "kWh", align: "right", render: (v) => fmtNum(v, 1) }, { key: "tariff", label: "Tariff", align: "right" }, { key: "cost", label: "Cost", align: "right", render: (v) => fmtNum(v, 0) }, { key: "source", label: "Source" }] },
  inventory: { label: "Inventory", path: "/api/inventory", cols: [{ key: "snapshot_date", label: "Date" }, { key: "item_code", label: "Item" }, { key: "item_name", label: "Name" }, { key: "quantity_on_hand", label: "On hand", align: "right", render: (v) => fmtNum(v, 0) }, { key: "reorder_point", label: "Reorder pt", align: "right", render: (v) => fmtNum(v, 0) }, { key: "avg_daily_usage", label: "Daily usage", align: "right", render: (v) => fmtNum(v, 0) }] },
  maintenance: { label: "Maintenance", path: "/api/maintenance", cols: [{ key: "event_ts", label: "When", render: ts }, { key: "machine_code", label: "Machine" }, { key: "category", label: "Category" }, { key: "duration_min", label: "Minutes", align: "right" }, { key: "cost", label: "Cost", align: "right", render: (v) => fmtNum(v, 0) }] },
};
const DATASETS = ["production", "downtime", "energy", "inventory"] as const;

function ImportPanel() {
  const { refresh } = useApp();
  const [dataset, setDataset] = useState<(typeof DATASETS)[number]>("production");
  const [file, setFile] = useState<File | null>(null);
  const [mode, setMode] = useState("skip_invalid");
  const [force, setForce] = useState(false);
  const [result, setResult] = useState<any>(null);
  const [kind, setKind] = useState<"validate" | "import" | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const hist = useApi("/api/imports", {}, { filtered: false });
  const run = async (what: "validate" | "import") => {
    if (!file) return;
    setBusy(true); setErr(null); setResult(null);
    const fd = new FormData(); fd.append("dataset", dataset); fd.append("file", file); fd.append("mode", mode); fd.append("force", String(force));
    try { const r = await upload(what === "validate" ? "/api/imports/validate" : "/api/imports", fd); setResult(r); setKind(what); if (what === "import") refresh(); }
    catch (e) { setErr(e instanceof ApiError ? `${e.message}` : String(e)); } finally { setBusy(false); }
  };
  return (
    <div className="space-y-4">
      <Card title="Import a CSV" subtitle="Validate first (nothing is written), then import. Invalid rows never reach the database.">
        <div className="grid gap-3 md:grid-cols-4">
          <div><label className="label" htmlFor="i-ds">Dataset</label><select id="i-ds" className="input w-full" value={dataset} onChange={(e) => setDataset(e.target.value as typeof dataset)}>{DATASETS.map((d) => <option key={d}>{d}</option>)}</select></div>
          <div className="md:col-span-2"><label className="label" htmlFor="i-file">CSV file (max 5 MB, UTF-8)</label><input id="i-file" type="file" accept=".csv,text/csv" className="input w-full" onChange={(e) => { setFile(e.target.files?.[0] ?? null); setResult(null); setErr(null); }} /></div>
          <div><label className="label" htmlFor="i-mode">On invalid rows</label><select id="i-mode" className="input w-full" value={mode} onChange={(e) => setMode(e.target.value)}><option value="skip_invalid">Import valid rows, report the rest</option><option value="all_or_nothing">Reject the whole file</option></select></div>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <button className="btn" disabled={!file || busy} onClick={() => run("validate")}>Validate and preview</button>
          <button className="btn btn-primary" disabled={!file || busy} onClick={() => run("import")}>Import</button>
          <label className="flex items-center gap-1.5 text-xs text-slate-600"><input type="checkbox" checked={force} onChange={(e) => setForce(e.target.checked)} /> Allow re-importing an identical file</label>
          <a className="btn" href={downloadUrl(`/api/imports/templates/${dataset}`)} download>Download {dataset} template</a>
        </div>
        {err && <div className="mt-3"><ErrorBox message={err} /></div>}
        {result && (
          <div className="mt-3" role="status">
            <Note tone={result.rows_rejected ? "warn" : "info"}>
              {kind === "validate" ? "Validation only, nothing was imported. " : `${result.message ?? ""} `}
              {fmtNum(result.rows_total)} rows read · {fmtNum(result.rows_valid)} valid · {fmtNum(result.rows_rejected)} rejected ({fmtNum(result.rows_duplicate)} duplicates).
              {kind === "import" && <> Imported <strong>{fmtNum(result.rows_imported)}</strong>.</>}
            </Note>
            {result.errors.length > 0 && <div className="mt-2"><h3 className="mb-1 text-xs font-semibold">Rejected rows{result.errors_truncated ? " (first 200)" : ""}</h3>
              <DataTable rows={result.errors} pageSize={8} cols={[{ key: "row", label: "CSV row", align: "right" }, { key: "column", label: "Column" }, { key: "message", label: "Problem" }]} /></div>}
            {result.preview.length > 0 && <div className="mt-2"><h3 className="mb-1 text-xs font-semibold">Preview of valid rows</h3><DataTable rows={result.preview} pageSize={5} cols={Object.keys(result.preview[0]).map((k) => ({ key: k, label: k.replace(/_/g, " ") }))} /></div>}
          </div>
        )}
      </Card>
      <Card title="Import history" subtitle="Most recent first">
        <Async res={hist} empty={(d) => !d.length}>{(d) => <DataTable rows={d} pageSize={8} initialSort={{ key: "id", desc: true }} cols={[{ key: "id", label: "#" }, { key: "created_at", label: "When", render: fmtDateTime }, { key: "dataset", label: "Dataset" }, { key: "filename", label: "File" },
          { key: "status", label: "Status", render: (v) => <Badge kind={v === "success" ? "green" : v === "partial" ? "amber" : "red"}>{v}</Badge> }, { key: "rows_accepted", label: "Accepted", align: "right" }, { key: "rows_rejected", label: "Rejected", align: "right" }, { key: "message", label: "Message" }]} />}</Async>
      </Card>
    </div>
  );
}

function DemoPanel() {
  const { config, refresh } = useApp();
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const gen = async (force: boolean) => {
    setErr(null); setMsg(null);
    try { const r = await send("POST", "/api/demo/generate", undefined, { force }); setMsg(`Generated ${r.production_records} production records from ${r.start} to ${r.end}.`); refresh(); }
    catch (e: any) { setErr(e.message); }
  };
  return (
    <Card title="Simulated demo dataset" subtitle="Fixed random seed (reproducible values). Dates end yesterday.">
      <p className="mb-3 text-sm text-slate-700">{config?.production_records ? `${fmtNum(config.production_records)} production records are loaded.` : "No data loaded yet."} The dataset is fictional: 3 lines, 10 machines, 8 products, 3 shifts, 90 days, with a few deliberately planted problems for the analytics to find.</p>
      <div className="flex flex-wrap gap-2"><button className="btn btn-primary" onClick={() => gen(false)} disabled={!!config?.production_records}>Generate demo data</button>
        <button className="btn" onClick={() => { if (confirm("This deletes ALL production, downtime, energy, inventory, recommendation and savings data, including imports, then regenerates the demo dataset. Continue?")) void gen(true); }}>Wipe and regenerate</button></div>
      {msg && <div className="mt-2"><Note>{msg}</Note></div>}{err && <div className="mt-2"><ErrorBox message={err} /></div>}
    </Card>
  );
}

export default function DataExplorer() {
  const [params] = useSearchParams();
  const { setFilters, filters } = useApp();
  const [tab, setTab] = useState(params.get("dataset") && TABS[params.get("dataset")!] ? params.get("dataset")! : "production");
  const machine = params.get("machine") ?? undefined;
  const date = params.get("date") ?? undefined;
  useEffect(() => { if (date) setFilters({ ...filters, date_from: date, date_to: date }); /* eslint-disable-next-line */ }, [date]);
  const t = TABS[tab];
  return (
    <>
      <PageHeader title="Data Explorer" subtitle="Browse the underlying records, import authorised CSV data, and export. Filters above apply to the record views." actions={tab in TABS && ["production", "downtime", "quality", "energy", "inventory"].includes(tab) ? <ExportButton path={`/api/export/${tab}`} /> : undefined} />
      <div className="mb-3 flex flex-wrap gap-1" role="tablist">{[...Object.entries(TABS).map(([k, v]) => [k, v.label]), ["import", "Import CSV"], ["demo", "Demo data"]].map(([k, l]) => (
        <button key={k} role="tab" aria-selected={tab === k} className={`btn ${tab === k ? "btn-primary" : ""}`} onClick={() => setTab(k)}>{l}</button>))}</div>
      {tab === "import" ? <ImportPanel /> : tab === "demo" ? <DemoPanel /> : <Card title={`${t.label} records`}>{machine && tab === "production" && <p className="mb-2 text-xs text-slate-600">Showing machine {machine}{date ? ` on ${date}` : ""} (from Root Cause Explorer).</p>}<ServerTable path={t.path} cols={t.cols} extra={machine && tab === "production" ? { machine_code: machine } : {}} /></Card>}
    </>
  );
}
