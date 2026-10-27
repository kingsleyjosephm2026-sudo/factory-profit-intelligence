import { RefreshCw } from "lucide-react";
import { useState } from "react";
import { send } from "../api";
import { Async, Badge, Card, ErrorBox, Note, PageHeader } from "../components/ui";
import { fmtDateTime, fmtMoney } from "../format";
import { useApi } from "../hooks";
import { useApp } from "../state";

const STATUSES = ["Open", "In progress", "Resolved", "Dismissed"] as const;
const SEV: Record<string, "red" | "amber" | "slate"> = { High: "red", Medium: "amber", Low: "slate" };

function RecCard({ r, onChange, cur }: { r: any; onChange: () => void; cur: string }) {
  const [notes, setNotes] = useState<string>(r.notes);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const patch = async (body: Record<string, string>) => {
    setBusy(true); setErr(null);
    try { await send("PATCH", `/api/recommendations/${r.id}`, body); setSaved(true); setTimeout(() => setSaved(false), 2000); onChange(); }
    catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  };
  return (
    <article className="card p-4" aria-label={r.title}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <div className="mb-1 flex flex-wrap items-center gap-2"><Badge kind={SEV[r.severity]}>{r.severity} severity</Badge><Badge kind="blue">Confidence: {r.confidence}</Badge><Badge>{r.entity_type}: {r.entity_name}</Badge>{!r.active && <Badge kind="amber">No longer triggered on latest data</Badge>}</div>
          <h3 className="text-sm font-semibold text-slate-900">{r.title}</h3>
        </div>
        <div className="flex items-center gap-2">
          <label className="sr-only" htmlFor={`st-${r.id}`}>Status</label>
          <select id={`st-${r.id}`} className="input" value={r.status} disabled={busy} onChange={(e) => patch({ status: e.target.value })}>{STATUSES.map((s) => <option key={s}>{s}</option>)}</select>
          {saved && <span className="text-xs text-green-700" role="status">Saved</span>}
        </div>
      </div>
      <dl className="mt-3 grid gap-3 text-sm md:grid-cols-2">
        <div><dt className="text-xs font-semibold text-slate-500">Evidence</dt><dd>{r.evidence}</dd></div>
        <div><dt className="text-xs font-semibold text-slate-500">Recommended next action</dt><dd>{r.next_action}</dd></div>
        <div><dt className="text-xs font-semibold text-slate-500">Triggering metric</dt><dd>{r.metric.replace(/_/g, " ")}: <strong>{r.metric_value}</strong> (threshold {r.threshold})</dd></div>
        <div><dt className="text-xs font-semibold text-slate-500">Estimated opportunity (unverified)</dt><dd>{r.estimated_opportunity === null ? "Not claimed" : <><strong>{fmtMoney(r.estimated_opportunity, cur, true)}</strong> <span className="text-slate-500">{r.opportunity_basis}</span></>}</dd></div>
      </dl>
      <details className="mt-2 text-xs text-slate-600"><summary className="cursor-pointer font-medium">Calculation method</summary><p className="mt-1">{r.calculation_method}</p><p className="mt-1">Window {r.window_start} to {r.window_end}. Evaluated {fmtDateTime(r.last_evaluated_at)}.</p></details>
      <div className="mt-3">
        <label className="label" htmlFor={`n-${r.id}`}>Notes</label>
        <div className="flex gap-2"><textarea id={`n-${r.id}`} className="input w-full" rows={2} value={notes} maxLength={4000} onChange={(e) => setNotes(e.target.value)} placeholder="Add investigation notes" />
          <button className="btn self-start" disabled={busy || notes === r.notes} onClick={() => patch({ notes })}>Save notes</button></div>
      </div>
      {err && <div className="mt-2"><ErrorBox message={err} /></div>}
    </article>
  );
}

export default function Recommendations() {
  const { config, refresh } = useApp();
  const [status, setStatus] = useState("");
  const [sev, setSev] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const res = useApi("/api/recommendations", { status, severity: sev }, { filtered: false });
  const run = async () => {
    setBusy(true); setErr(null);
    try { const r = await send("POST", "/api/recommendations/refresh"); setMsg(`Evaluated rules: ${r.created} new, ${r.updated} updated, ${r.deactivated} no longer triggered.`); refresh(); }
    catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  };
  return (
    <>
      <PageHeader title="Recommendations" subtitle="Deterministic rules over the latest 30 days. Status and notes you set are saved and survive re-evaluation."
        actions={<>
          <select className="input" aria-label="Filter by status" value={status} onChange={(e) => setStatus(e.target.value)}><option value="">All statuses</option>{STATUSES.map((s) => <option key={s}>{s}</option>)}</select>
          <select className="input" aria-label="Filter by severity" value={sev} onChange={(e) => setSev(e.target.value)}><option value="">All severities</option><option>High</option><option>Medium</option><option>Low</option></select>
          <button className="btn btn-primary" disabled={busy} onClick={run}><RefreshCw size={14} className={busy ? "animate-spin" : ""} /> Re-evaluate rules</button></>} />
      {msg && <div className="mb-3"><Note>{msg}</Note></div>}
      {err && <div className="mb-3"><ErrorBox message={err} /></div>}
      <Async res={res} empty={(d) => !d.length}>
        {(list) => <div className="space-y-3">{list.map((r: any) => <RecCard key={`${r.id}-${r.updated_at}`} r={r} cur={config?.currency ?? "INR"} onChange={refresh} />)}</div>}
      </Async>
      {res.data && res.data.length === 0 && !res.loading && <p className="mt-3 text-sm text-slate-600">No recommendations match. Click <strong>Re-evaluate rules</strong> to run the rule engine on the current data.</p>}
    </>
  );
}
