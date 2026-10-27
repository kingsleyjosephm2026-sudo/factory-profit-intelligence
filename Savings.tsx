import { CheckCircle2, XCircle } from "lucide-react";
import { useState } from "react";
import { send } from "../api";
import { Async, Badge, Card, ErrorBox, Note, PageHeader } from "../components/ui";
import { fmtMoney } from "../format";
import { useApi } from "../hooks";
import { useApp } from "../state";

const KIND: Record<string, "slate" | "blue" | "amber" | "green"> = { identified: "slate", forecast: "blue", estimated: "amber", verified: "green" };
const LABEL: Record<string, string> = { identified: "Opportunity identified", forecast: "Savings forecast", estimated: "Savings estimated", verified: "Savings verified" };

function Evidence({ ev, cur }: { ev: any; cur: string }) {
  if (!ev?.checks) return null;
  return (
    <div className="mt-3 rounded-lg bg-slate-50 p-3 text-xs text-slate-700">
      <div><strong>Formula:</strong> <span className="font-mono">{ev.formula}</span></div>
      {ev.baseline && <div className="mt-1"><strong>Baseline:</strong> {ev.baseline.days_with_data}/{ev.baseline.days_total} days with data · cost rate {ev.baseline_rate?.toFixed(4)} · {ev.natural_metric} {ev.baseline.natural?.toFixed(3)}</div>}
      {ev.post && <div><strong>Post-intervention:</strong> {ev.post.days_with_data}/{ev.post.days_total} days with data · cost rate {ev.post_rate?.toFixed(4)} · {ev.natural_metric} {ev.post.natural?.toFixed(3)}{ev.t_statistic != null && <> · t = {ev.t_statistic.toFixed(2)}</>}</div>}
      <ul className="mt-2 space-y-1" aria-label="Evidence checks">{ev.checks.map((c: any) => (
        <li key={c.name} className="flex gap-1.5">{c.passed ? <CheckCircle2 size={14} className="mt-0.5 shrink-0 text-green-600" aria-label="passed" /> : <XCircle size={14} className="mt-0.5 shrink-0 text-red-600" aria-label="failed" />}<span><strong>{c.name}.</strong> {c.detail}</span></li>))}
      </ul>
      <p className="mt-2 font-medium">{ev.caveat}</p>
      <details className="mt-1"><summary className="cursor-pointer">Evidence required for verification</summary><ul className="ml-4 mt-1 list-disc">{ev.required_evidence.map((r: string) => <li key={r}>{r}</li>)}</ul></details>
    </div>
  );
}

function NewForm({ onDone }: { onDone: () => void }) {
  const { lines, machines, config } = useApp();
  const end = config?.data_to ?? "";
  const [f, setF] = useState<Record<string, any>>({ category: "downtime", scope_type: "factory", value_source: "computed", title: "", assumptions: "" });
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: string, v: any) => setF((p) => ({ ...p, [k]: v === "" ? undefined : v }));
  const submit = async (e: React.FormEvent) => {
    e.preventDefault(); setBusy(true); setErr(null);
    try {
      const body = { ...f, scope_id: f.scope_type === "factory" ? undefined : Number(f.scope_id), expected_savings: f.expected_savings === undefined ? undefined : Number(f.expected_savings),
        baseline_value: f.baseline_value === undefined ? undefined : Number(f.baseline_value), post_value: f.post_value === undefined ? undefined : Number(f.post_value), manual_volume: f.manual_volume === undefined ? undefined : Number(f.manual_volume) };
      await send("POST", "/api/savings", body); onDone();
    } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  };
  const manual = f.value_source === "manual";
  return (
    <form onSubmit={submit} className="grid gap-3 md:grid-cols-3" aria-label="New savings initiative">
      <div className="md:col-span-2"><label className="label" htmlFor="s-title">Initiative title</label><input id="s-title" required minLength={3} className="input w-full" value={f.title} onChange={(e) => set("title", e.target.value)} /></div>
      <div><label className="label" htmlFor="s-cat">Problem category</label><select id="s-cat" className="input w-full" value={f.category} onChange={(e) => set("category", e.target.value)}><option value="downtime">Downtime</option><option value="quality">Quality</option><option value="energy">Energy</option><option value="material">Material waste</option></select></div>
      <div><label className="label" htmlFor="s-scope">Scope</label><select id="s-scope" className="input w-full" value={f.scope_type} onChange={(e) => { set("scope_type", e.target.value); set("scope_id", ""); }}><option value="factory">Whole factory</option><option value="line">Production line</option><option value="machine">Machine</option></select></div>
      {f.scope_type !== "factory" && <div><label className="label" htmlFor="s-sid">{f.scope_type === "line" ? "Line" : "Machine"}</label><select id="s-sid" required className="input w-full" value={f.scope_id ?? ""} onChange={(e) => set("scope_id", e.target.value)}><option value="">Select…</option>{(f.scope_type === "line" ? lines.map((l) => [l.id, l.name]) : machines.map((m) => [m.id, m.code])).map(([id, n]) => <option key={id} value={id}>{n}</option>)}</select></div>}
      <div><label className="label" htmlFor="s-bs">Baseline start</label><input id="s-bs" type="date" className="input w-full" max={end} onChange={(e) => set("baseline_start", e.target.value)} /></div>
      <div><label className="label" htmlFor="s-be">Baseline end</label><input id="s-be" type="date" className="input w-full" max={end} onChange={(e) => set("baseline_end", e.target.value)} /></div>
      <div><label className="label" htmlFor="s-iv">Intervention date</label><input id="s-iv" type="date" className="input w-full" onChange={(e) => set("intervention_date", e.target.value)} /></div>
      <div><label className="label" htmlFor="s-ps">Post-intervention start</label><input id="s-ps" type="date" className="input w-full" onChange={(e) => set("post_start", e.target.value)} /></div>
      <div><label className="label" htmlFor="s-pe">Post-intervention end</label><input id="s-pe" type="date" className="input w-full" onChange={(e) => set("post_end", e.target.value)} /></div>
      <div><label className="label" htmlFor="s-ex">Expected savings ({config?.currency})</label><input id="s-ex" type="number" min={0} className="input w-full" onChange={(e) => set("expected_savings", e.target.value)} /></div>
      <div><label className="label" htmlFor="s-src">Baseline and post values</label><select id="s-src" className="input w-full" value={f.value_source} onChange={(e) => set("value_source", e.target.value)}><option value="computed">Computed from loaded data (can be verified)</option><option value="manual">Entered manually (estimate only)</option></select></div>
      {manual && <>
        <div><label className="label" htmlFor="s-bv">Baseline cost rate</label><input id="s-bv" type="number" step="any" className="input w-full" onChange={(e) => set("baseline_value", e.target.value)} /></div>
        <div><label className="label" htmlFor="s-pv">Post cost rate</label><input id="s-pv" type="number" step="any" className="input w-full" onChange={(e) => set("post_value", e.target.value)} /></div>
        <div><label className="label" htmlFor="s-vol">Post volume (driver units)</label><input id="s-vol" type="number" min={0} className="input w-full" onChange={(e) => set("manual_volume", e.target.value)} /></div></>}
      <div className="md:col-span-3"><label className="label" htmlFor="s-as">Financial assumptions (required for verification)</label><textarea id="s-as" rows={2} className="input w-full" value={f.assumptions} onChange={(e) => set("assumptions", e.target.value ?? "")} /></div>
      <div className="md:col-span-3"><label className="label" htmlFor="s-nt">Notes</label><input id="s-nt" className="input w-full" onChange={(e) => set("notes", e.target.value)} /></div>
      <div className="md:col-span-3 flex items-center gap-3"><button className="btn btn-primary" disabled={busy}>Create and evaluate</button><span className="text-xs text-slate-500">The evidence status is calculated by the server. It cannot be typed in.</span></div>
      {err && <div className="md:col-span-3"><ErrorBox message={err} /></div>}
    </form>
  );
}

export default function Savings() {
  const { config, refresh } = useApp();
  const cur = config?.currency ?? "INR";
  const res = useApi("/api/savings", {}, { filtered: false });
  const [show, setShow] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const act = async (fn: () => Promise<unknown>) => { setErr(null); try { await fn(); refresh(); } catch (e: any) { setErr(e.message); } };
  return (
    <>
      <PageHeader title="Savings Verification" subtitle="Distinguishes identified, forecast, estimated and verified savings. 'Verified' is earned from evidence in the data, never from a typed number."
        actions={<button className="btn btn-primary" onClick={() => setShow(!show)}>{show ? "Close form" : "New initiative"}</button>} />
      {show && <Card className="mb-4" title="New savings initiative"><NewForm onDone={() => { setShow(false); refresh(); }} /></Card>}
      {err && <div className="mb-3"><ErrorBox message={err} /></div>}
      <Async res={res} empty={(d) => !d.items.length}>
        {(d) => (
          <>
            <div className="mb-4 grid grid-cols-2 gap-3 xl:grid-cols-4">
              {(["identified", "forecast", "estimated", "verified"] as const).map((s) => (
                <div key={s} className="card p-4"><Badge kind={KIND[s]}>{LABEL[s]}</Badge><div className="mt-2 text-2xl font-semibold tabular-nums">{fmtMoney(d.totals[s], cur, true)}</div><div className="text-xs text-slate-500">{s === "identified" || s === "forecast" ? "Expected, unmeasured" : "Calculated from data"}</div></div>))}
            </div>
            <div className="space-y-3">{d.items.map((i: any) => (
              <article key={i.id} className="card p-4" aria-label={i.title}>
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div><div className="mb-1 flex flex-wrap items-center gap-2"><Badge kind={KIND[i.evidence_status]}>{LABEL[i.evidence_status]}</Badge><Badge>{i.category}</Badge><Badge>{i.scope_type}{i.scope_id ? ` #${i.scope_id}` : ""}</Badge><Badge>{i.value_source}</Badge></div><h3 className="text-sm font-semibold">{i.title}</h3></div>
                  <div className="flex gap-2"><button className="btn" onClick={() => act(() => send("POST", `/api/savings/${i.id}/evaluate`))}>Re-evaluate</button><button className="btn" onClick={() => { if (confirm("Delete this initiative?")) void act(() => send("DELETE", `/api/savings/${i.id}`)); }}>Delete</button></div>
                </div>
                <dl className="mt-2 grid gap-2 text-sm md:grid-cols-4">
                  <div><dt className="text-xs text-slate-500">Expected savings</dt><dd>{i.expected_savings != null ? fmtMoney(i.expected_savings, cur, true) : "n/a"}</dd></div>
                  <div><dt className="text-xs text-slate-500">Calculated savings</dt><dd>{i.calculated_savings != null ? fmtMoney(i.calculated_savings, cur, true) : "not measured"}</dd></div>
                  <div><dt className="text-xs text-slate-500">Baseline period</dt><dd>{i.baseline_start ?? "n/a"} to {i.baseline_end ?? "n/a"}</dd></div>
                  <div><dt className="text-xs text-slate-500">Intervention / post period</dt><dd>{i.intervention_date ?? "n/a"} · {i.post_start ?? "n/a"} to {i.post_end ?? "n/a"}</dd></div>
                </dl>
                {i.assumptions && <p className="mt-2 text-xs text-slate-600"><strong>Assumptions:</strong> {i.assumptions}</p>}
                <Evidence ev={i.evidence} cur={cur} />
              </article>))}
            </div>
          </>
        )}
      </Async>
      {res.data && !res.data.items.length && !res.loading && <Note>No initiatives yet. Create one from a recommendation: define a baseline of at least 28 days before the intervention date and at least 14 days after it.</Note>}
    </>
  );
}
