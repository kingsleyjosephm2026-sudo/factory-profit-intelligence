import { AlertTriangle, ArrowDownRight, ArrowUpRight, ChevronLeft, ChevronRight, Download, Info, Loader2, Minus } from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { downloadUrl, get, type KpiCard, type Row } from "../api";
import { fmtValue, tone } from "../format";
import type { Result } from "../hooks";
import { useApp } from "../state";

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: ReactNode }) {
  return (
    <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-xl font-semibold text-slate-900">{title}</h1>
        {subtitle && <p className="mt-0.5 max-w-3xl text-sm text-slate-600">{subtitle}</p>}
      </div>
      <div className="flex flex-wrap items-center gap-2">{actions}</div>
    </div>
  );
}

export function Card({ title, subtitle, actions, children, className = "" }: { title?: string; subtitle?: string; actions?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`card p-4 ${className}`}>
      {(title || actions) && (
        <header className="mb-3 flex items-start justify-between gap-2">
          <div>
            {title && <h2 className="text-sm font-semibold text-slate-900">{title}</h2>}
            {subtitle && <p className="mt-0.5 text-xs text-slate-500">{subtitle}</p>}
          </div>
          {actions}
        </header>
      )}
      {children}
    </section>
  );
}

export function Note({ children, tone: t = "info" }: { children: ReactNode; tone?: "info" | "warn" }) {
  const cls = t === "warn" ? "border-amber-300 bg-amber-50 text-amber-900" : "border-blue-200 bg-blue-50 text-blue-900";
  return (
    <div role="note" className={`flex gap-2 rounded-lg border px-3 py-2 text-xs ${cls}`}>
      {t === "warn" ? <AlertTriangle size={14} className="mt-0.5 shrink-0" /> : <Info size={14} className="mt-0.5 shrink-0" />}
      <div>{children}</div>
    </div>
  );
}

export function Badge({ children, kind = "slate" }: { children: ReactNode; kind?: "slate" | "red" | "amber" | "green" | "blue" }) {
  const cls = { slate: "bg-slate-100 text-slate-700", red: "bg-red-100 text-red-800", amber: "bg-amber-100 text-amber-900", green: "bg-green-100 text-green-800", blue: "bg-blue-100 text-blue-800" }[kind];
  return <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${cls}`}>{children}</span>;
}

/** Renders loading, error, empty and success states for a fetch result. */
export function Async<T>({ res, children, empty }: { res: Result<T>; children: (d: T) => ReactNode; empty?: (d: T) => boolean }) {
  if (res.error && !res.data) return <ErrorBox message={res.error} />;
  if (!res.data) return <Loading />;
  return (
    <div className={res.loading ? "opacity-60 transition-opacity" : ""} aria-busy={res.loading}>
      {res.error && <div className="mb-2"><ErrorBox message={res.error} /></div>}
      {empty?.(res.data) ? <EmptyState /> : children(res.data)}
    </div>
  );
}

export function Loading() {
  return <div role="status" className="flex items-center gap-2 py-8 text-sm text-slate-500"><Loader2 className="animate-spin" size={16} /> Loading…</div>;
}

export function ErrorBox({ message }: { message: string }) {
  return <div role="alert" className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800"><AlertTriangle size={16} className="mt-0.5 shrink-0" /> {message}</div>;
}

export function EmptyState({ message = "No data for the selected filters. Widen the date range or clear a filter." }: { message?: string }) {
  return <div className="rounded-lg border border-dashed border-slate-300 py-8 text-center text-sm text-slate-500">{message}</div>;
}

export function ExportButton({ path, params, label = "Export CSV" }: { path: string; params?: Record<string, unknown>; label?: string }) {
  const { filters } = useApp();
  return <a className="btn" href={downloadUrl(path, { ...filters, ...params })} download><Download size={14} /> {label}</a>;
}

// ----------------------------------------------------------------------------- metric definitions
let metricsCache: Promise<Record<string, Row>> | null = null;
export function useMetricDocs(): Record<string, Row> {
  const [docs, setDocs] = useState<Record<string, Row>>({});
  useEffect(() => {
    metricsCache ??= get<Record<string, Row>>("/api/metrics");
    metricsCache.then(setDocs).catch(() => { metricsCache = null; });
  }, []);
  return docs;
}

export function MetricDefinition({ docKey }: { docKey: string | null }) {
  const docs = useMetricDocs();
  const [open, setOpen] = useState(false);
  const d = docKey ? docs[docKey] : null;
  if (!d) return null;
  return (
    <span className="relative">
      <button type="button" className="rounded p-0.5 text-slate-400 hover:text-slate-700 focus-visible:ring-2 focus-visible:ring-brand-500" aria-label={`Definition of ${d.label}`} aria-expanded={open} onClick={() => setOpen(!open)}>
        <Info size={14} />
      </button>
      {open && (
        <div role="dialog" className="absolute right-0 z-30 mt-1 w-72 rounded-lg border border-slate-200 bg-white p-3 text-left text-xs shadow-lg">
          <div className="mb-1 flex items-center justify-between"><strong className="text-sm">{d.label}</strong><Badge kind={d.type === "measured" ? "green" : d.type === "calculated" ? "blue" : "amber"}>{d.type}</Badge></div>
          <dl className="space-y-1 text-slate-700">
            <div><dt className="font-semibold">Formula</dt><dd className="font-mono">{d.formula}</dd></div>
            <div><dt className="font-semibold">Unit</dt><dd>{d.unit}</dd></div>
            <div><dt className="font-semibold">Assumptions</dt><dd>{d.assumptions}</dd></div>
            <div><dt className="font-semibold">Limitations</dt><dd>{d.limitations}</dd></div>
          </dl>
          <button className="mt-2 text-brand-600 underline" onClick={() => setOpen(false)}>Close</button>
        </div>
      )}
    </span>
  );
}

export function Kpi({ card, currency }: { card: KpiCard; currency: string }) {
  const t = tone(card.abs_diff, card.better);
  const color = t === "good" ? "text-green-700" : t === "bad" ? "text-red-700" : "text-slate-500";
  const Arrow = card.abs_diff === null || card.abs_diff === 0 ? Minus : card.abs_diff > 0 ? ArrowUpRight : ArrowDownRight;
  return (
    <div className="card p-4" data-testid={`kpi-${card.key}`}>
      <div className="flex items-start justify-between gap-1">
        <span className="text-xs font-medium text-slate-600">{card.label}</span>
        <MetricDefinition docKey={card.definition_key} />
      </div>
      <div className="mt-1 text-2xl font-semibold tabular-nums text-slate-900">{fmtValue(card.value, card.unit, currency)}</div>
      {card.key === "recs" ? (
        <div className="mt-1 text-xs text-slate-500">Open, severity High</div>
      ) : card.abs_diff === null ? (
        <div className="mt-1 text-xs text-slate-500">No previous-period data</div>
      ) : (
        <div className={`mt-1 flex items-center gap-1 text-xs ${color}`} title="Versus the previous period of equal length">
          <Arrow size={14} aria-hidden />
          <span>{card.abs_diff > 0 ? "+" : ""}{fmtValue(card.abs_diff, card.unit, currency)}</span>
          <span>{card.pct_diff === null ? "(% n/a)" : `(${card.pct_diff > 0 ? "+" : ""}${card.pct_diff.toFixed(1)}%)`}</span>
          <span className="sr-only">{t === "good" ? "improvement" : t === "bad" ? "deterioration" : "no change"}</span>
        </div>
      )}
      {card.previous !== null && card.key !== "recs" && <div className="mt-0.5 text-[11px] text-slate-400">Previous: {fmtValue(card.previous, card.unit, currency)}</div>}
    </div>
  );
}

// ----------------------------------------------------------------------------- tables
export interface Col { key: string; label: string; render?: (v: any, row: Row) => ReactNode; align?: "right"; sortable?: boolean }

export function DataTable({ rows, cols, pageSize = 10, onRow, initialSort, caption }: { rows: Row[]; cols: Col[]; pageSize?: number; onRow?: (r: Row) => void; initialSort?: { key: string; desc: boolean }; caption?: string }) {
  const [sort, setSort] = useState<{ key: string; desc: boolean } | null>(initialSort ?? null);
  const [page, setPage] = useState(0);
  const sorted = useMemo(() => {
    if (!sort) return rows;
    const out = [...rows];
    out.sort((a, b) => {
      const x = a[sort.key], y = b[sort.key];
      if (x === y) return 0;
      if (x === null || x === undefined) return 1;
      if (y === null || y === undefined) return -1;
      return (x > y ? 1 : -1) * (sort.desc ? -1 : 1);
    });
    return out;
  }, [rows, sort]);
  useEffect(() => setPage(0), [rows]);
  const pages = Math.max(1, Math.ceil(sorted.length / pageSize));
  const view = sorted.slice(page * pageSize, page * pageSize + pageSize);
  if (!rows.length) return <EmptyState />;
  return (
    <div>
      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-slate-200">
          {caption && <caption className="sr-only">{caption}</caption>}
          <thead><tr>
            {cols.map((c) => (
              <th key={c.key} className={`th ${c.align === "right" ? "text-right" : ""}`} aria-sort={sort?.key === c.key ? (sort.desc ? "descending" : "ascending") : "none"}>
                {c.sortable === false ? c.label : (
                  <button className="inline-flex items-center gap-1 uppercase hover:text-slate-800" onClick={() => setSort(sort?.key === c.key ? { key: c.key, desc: !sort.desc } : { key: c.key, desc: true })}>
                    {c.label}{sort?.key === c.key && <span aria-hidden>{sort.desc ? "▼" : "▲"}</span>}
                  </button>
                )}
              </th>
            ))}
          </tr></thead>
          <tbody className="divide-y divide-slate-100">
            {view.map((r, i) => (
              <tr key={i} className={onRow ? "cursor-pointer hover:bg-slate-50" : "hover:bg-slate-50"} onClick={onRow ? () => onRow(r) : undefined}>
                {cols.map((c) => <td key={c.key} className={`td ${c.align === "right" ? "text-right tabular-nums" : ""}`}>{c.render ? c.render(r[c.key], r) : (r[c.key] ?? "n/a")}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {pages > 1 && (
        <div className="mt-2 flex items-center justify-end gap-2 text-xs text-slate-600">
          <span>Page {page + 1} of {pages} · {sorted.length} rows</span>
          <button className="btn px-2 py-1" disabled={page === 0} onClick={() => setPage(page - 1)} aria-label="Previous page"><ChevronLeft size={14} /></button>
          <button className="btn px-2 py-1" disabled={page >= pages - 1} onClick={() => setPage(page + 1)} aria-label="Next page"><ChevronRight size={14} /></button>
        </div>
      )}
    </div>
  );
}

/** Server-paginated table for large record collections. */
export function ServerTable({ path, cols, pageSize = 20, extra = {} }: { path: string; cols: Col[]; pageSize?: number; extra?: Record<string, unknown> }) {
  const { filters, version } = useApp();
  const [page, setPage] = useState(1);
  const [res, setRes] = useState<{ total: number; items: Row[] } | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const key = JSON.stringify([filters, extra, path]);
  useEffect(() => setPage(1), [key]);
  useEffect(() => {
    const ctl = new AbortController();
    get(path, { ...filters, ...extra, page, page_size: pageSize }, ctl.signal).then((r) => { setRes(r); setErr(null); }).catch((e) => { if (e.name !== "AbortError") setErr(e.message); });
    return () => ctl.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, page, pageSize, version]);
  if (err) return <ErrorBox message={err} />;
  if (!res) return <Loading />;
  const pages = Math.max(1, Math.ceil(res.total / pageSize));
  return (
    <div>
      {res.items.length === 0 ? <EmptyState /> : (
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-slate-200">
            <thead><tr>{cols.map((c) => <th key={c.key} className={`th ${c.align === "right" ? "text-right" : ""}`}>{c.label}</th>)}</tr></thead>
            <tbody className="divide-y divide-slate-100">
              {res.items.map((r, i) => <tr key={i} className="hover:bg-slate-50">{cols.map((c) => <td key={c.key} className={`td ${c.align === "right" ? "text-right tabular-nums" : ""}`}>{c.render ? c.render(r[c.key], r) : String(r[c.key] ?? "n/a")}</td>)}</tr>)}
            </tbody>
          </table>
        </div>
      )}
      <div className="mt-2 flex items-center justify-end gap-2 text-xs text-slate-600">
        <span>Page {page} of {pages} · {res.total.toLocaleString()} records</span>
        <button className="btn px-2 py-1" disabled={page <= 1} onClick={() => setPage(page - 1)} aria-label="Previous page"><ChevronLeft size={14} /></button>
        <button className="btn px-2 py-1" disabled={page >= pages} onClick={() => setPage(page + 1)} aria-label="Next page"><ChevronRight size={14} /></button>
      </div>
    </div>
  );
}
