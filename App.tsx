import { Activity, BarChart3, BookOpen, Boxes, Database, DollarSign, Factory, Gauge, GitBranch, Lightbulb, ListChecks, Menu, Pause, Play, RefreshCw, RotateCcw, SkipForward, TrendingDown, Zap, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { NavLink, Route, Routes } from "react-router-dom";
import { Badge, ErrorBox } from "./components/ui";
import { fmtDateTime } from "./format";
import { useApp } from "./state";
import Overview from "./pages/Overview";
import ProfitLeakage from "./pages/ProfitLeakage";
import { DowntimePage, EnergyPage, InventoryPage, ProductionPage, QualityPage } from "./pages/Domain";
import RootCause from "./pages/RootCause";
import Recommendations from "./pages/Recommendations";
import Savings from "./pages/Savings";
import DataExplorer from "./pages/DataExplorer";
import SettingsDocs from "./pages/SettingsDocs";

const NAV = [
  { to: "/", label: "Executive Overview", icon: Gauge },
  { to: "/profit-leakage", label: "Profit Leakage", icon: DollarSign },
  { to: "/production", label: "Production Analytics", icon: BarChart3 },
  { to: "/downtime", label: "Machine Downtime", icon: TrendingDown },
  { to: "/quality", label: "Quality and Defects", icon: ShieldCheck },
  { to: "/energy", label: "Energy Analytics", icon: Zap },
  { to: "/inventory", label: "Inventory Analysis", icon: Boxes },
  { to: "/root-cause", label: "Root Cause Explorer", icon: GitBranch },
  { to: "/recommendations", label: "Recommendations", icon: Lightbulb },
  { to: "/savings", label: "Savings Verification", icon: ListChecks },
  { to: "/data", label: "Data Explorer", icon: Database },
  { to: "/settings", label: "Settings & Docs", icon: BookOpen },
];

function FilterBar() {
  const { filters, setFilters, machines, products, lines, config } = useApp();
  const set = (patch: Record<string, unknown>) => setFilters({ ...filters, ...patch } as typeof filters);
  const num = (v: string) => (v ? Number(v) : undefined);
  return (
    <div className="flex flex-wrap items-end gap-2" role="search" aria-label="Global filters">
      <div><label className="label" htmlFor="f-from">From</label><input id="f-from" type="date" className="input" min={config?.data_from ?? undefined} max={filters.date_to} value={filters.date_from ?? ""} onChange={(e) => set({ date_from: e.target.value || undefined })} /></div>
      <div><label className="label" htmlFor="f-to">To</label><input id="f-to" type="date" className="input" min={filters.date_from} max={config?.data_to ?? undefined} value={filters.date_to ?? ""} onChange={(e) => set({ date_to: e.target.value || undefined })} /></div>
      <div><label className="label" htmlFor="f-line">Production line</label>
        <select id="f-line" className="input" value={filters.line_id ?? ""} onChange={(e) => set({ line_id: num(e.target.value), machine_id: undefined })}>
          <option value="">All lines</option>{lines.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
        </select></div>
      <div><label className="label" htmlFor="f-machine">Machine</label>
        <select id="f-machine" className="input" value={filters.machine_id ?? ""} onChange={(e) => set({ machine_id: num(e.target.value) })}>
          <option value="">All machines</option>{machines.filter((m) => !filters.line_id || m.line_id === filters.line_id).map((m) => <option key={m.id} value={m.id}>{m.code}</option>)}
        </select></div>
      <div><label className="label" htmlFor="f-product">Product</label>
        <select id="f-product" className="input" value={filters.product_id ?? ""} onChange={(e) => set({ product_id: num(e.target.value) })}>
          <option value="">All products</option>{products.map((p) => <option key={p.id} value={p.id}>{p.sku} {p.name}</option>)}
        </select></div>
      <div><label className="label" htmlFor="f-shift">Shift</label>
        <select id="f-shift" className="input" value={filters.shift ?? ""} onChange={(e) => set({ shift: e.target.value || undefined })}>
          <option value="">All shifts</option><option value="A">A (06-14)</option><option value="B">B (14-22)</option><option value="C">C (22-06)</option>
        </select></div>
      <button className="btn" onClick={() => setFilters({ date_from: filters.date_from, date_to: filters.date_to })}>Clear filters</button>
    </div>
  );
}

function LiveBar() {
  const { sim, simError, simAction, lastUpdated, refresh, config } = useApp();
  return (
    <div className="flex flex-wrap items-center gap-2 text-xs">
      <Badge kind="amber">{config?.data_label ?? "SIMULATED DEMO DATA"}</Badge>
      <span className="inline-flex items-center gap-1" title="Live mode writes simulated events into the dataset. It is not real factory telemetry.">
        <span className={`h-2 w-2 rounded-full ${simError ? "bg-red-500" : sim?.running ? "animate-pulse bg-green-500" : "bg-slate-400"}`} aria-hidden />
        <strong>{simError ? "API unavailable" : sim?.running ? "Live demo (simulated)" : "Live demo paused"}</strong>
      </span>
      <span className="text-slate-500">Updated {lastUpdated ? lastUpdated.toLocaleTimeString() : "never"}{sim?.simulated_clock ? ` · sim clock ${fmtDateTime(sim.simulated_clock)}` : ""}</span>
      {sim && <span className="text-slate-500">· {sim.simulated_rows.toLocaleString()} sim rows (cap {sim.retention_limit.toLocaleString()})</span>}
      {sim?.running ? <button className="btn px-2 py-1" onClick={() => simAction("pause")}><Pause size={12} /> Pause</button> : <button className="btn px-2 py-1" onClick={() => simAction("start")}><Play size={12} /> Resume</button>}
      <button className="btn px-2 py-1" onClick={() => simAction("tick")} title="Advance the simulation by one step"><SkipForward size={12} /> Step</button>
      <button className="btn px-2 py-1" onClick={() => { if (confirm("Remove all simulated live rows? Demo history and imports are kept.")) void simAction("reset"); }}><RotateCcw size={12} /> Reset simulation</button>
      <button className="btn px-2 py-1" onClick={refresh}><RefreshCw size={12} /> Refresh</button>
    </div>
  );
}

export default function App() {
  const { configError, config, sim, simError } = useApp();
  const [open, setOpen] = useState(false);
  return (
    <div className="flex min-h-screen">
      <aside className={`${open ? "block" : "hidden"} fixed inset-y-0 left-0 z-40 w-60 shrink-0 overflow-y-auto bg-slate-900 p-3 text-slate-200 lg:sticky lg:top-0 lg:block lg:h-screen`} aria-label="Primary">
        <div className="mb-4 flex items-center gap-2 px-2 py-2 text-white"><Factory size={20} /><span className="text-sm font-semibold leading-tight">Factory Profit<br />Intelligence</span></div>
        <nav className="space-y-0.5">
          {NAV.map(({ to, label, icon: Icon }) => (
            <NavLink key={to} to={to} end={to === "/"} onClick={() => setOpen(false)}
              className={({ isActive }) => `flex items-center gap-2 rounded-lg px-2.5 py-2 text-sm ${isActive ? "bg-brand-600 text-white" : "text-slate-300 hover:bg-slate-800"}`}>
              <Icon size={16} aria-hidden /> {label}
            </NavLink>
          ))}
        </nav>
        <p className="mt-6 px-2 text-[11px] leading-snug text-slate-400">Demo build. No authentication; not production-hardened. Data is simulated and not connected to real machinery.</p>
      </aside>
      <div className="min-w-0 flex-1">
        <header className="sticky top-0 z-30 border-b border-slate-200 bg-white/95 px-4 py-2 backdrop-blur">
          <div className="mb-2 flex items-center gap-2">
            <button className="btn px-2 lg:hidden" aria-label="Toggle navigation" onClick={() => setOpen(!open)}><Menu size={16} /></button>
            <Activity size={16} className="text-brand-600" aria-hidden />
            <LiveBar />
          </div>
          <FilterBar />
        </header>
        <main className="mx-auto max-w-[1400px] p-4">
          {configError && <div className="mb-3"><ErrorBox message={`${configError} The dashboard will refresh automatically once the API is reachable.`} /></div>}
          {config && config.production_records === 0 && (
            <div className="mb-3"><ErrorBox message="No data is loaded. Open Data Explorer and generate the simulated demo dataset, or import a CSV." /></div>
          )}
          {sim?.error && <div className="mb-3"><ErrorBox message={`Simulation error: ${sim.error}`} /></div>}
          {simError && !configError && <div className="mb-3"><ErrorBox message={simError} /></div>}
          <Routes>
            <Route path="/" element={<Overview />} />
            <Route path="/profit-leakage" element={<ProfitLeakage />} />
            <Route path="/production" element={<ProductionPage />} />
            <Route path="/downtime" element={<DowntimePage />} />
            <Route path="/quality" element={<QualityPage />} />
            <Route path="/energy" element={<EnergyPage />} />
            <Route path="/inventory" element={<InventoryPage />} />
            <Route path="/root-cause" element={<RootCause />} />
            <Route path="/recommendations" element={<Recommendations />} />
            <Route path="/savings" element={<Savings />} />
            <Route path="/data" element={<DataExplorer />} />
            <Route path="/settings" element={<SettingsDocs />} />
            <Route path="*" element={<ErrorBox message="Page not found." />} />
          </Routes>
        </main>
      </div>
    </div>
  );
}
