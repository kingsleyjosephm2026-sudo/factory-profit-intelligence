import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { get, send, type AppConfig, type Filters, type Row, type SimStatus } from "./api";

interface Ctx {
  filters: Filters;
  setFilters: (f: Filters) => void;
  config: AppConfig | null;
  configError: string | null;
  machines: Row[];
  products: Row[];
  lines: Row[];
  sim: SimStatus | null;
  simError: string | null;
  lastUpdated: Date | null;
  version: number; // changes when data changes (manual refresh or simulation tick)
  refresh: () => void;
  simAction: (a: "start" | "pause" | "reset" | "tick") => Promise<void>;
}

const AppCtx = createContext<Ctx>(null as unknown as Ctx);
export const useApp = () => useContext(AppCtx);

export function AppProvider({ children }: { children: ReactNode }) {
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [configError, setConfigError] = useState<string | null>(null);
  const [filters, setFilters] = useState<Filters>({});
  const [machines, setMachines] = useState<Row[]>([]);
  const [products, setProducts] = useState<Row[]>([]);
  const [lines, setLines] = useState<Row[]>([]);
  const [sim, setSim] = useState<SimStatus | null>(null);
  const [simError, setSimError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [manual, setManual] = useState(0);
  const initialised = useRef(false);

  const loadConfig = useCallback(async () => {
    try {
      const [c, mc, pr, fa] = await Promise.all([get<AppConfig>("/api/config"), get<Row[]>("/api/machines"), get<Row[]>("/api/products"), get<Row[]>("/api/factories")]);
      setConfig(c); setMachines(mc); setProducts(pr); setLines(fa.flatMap((f) => f.lines));
      setConfigError(null);
      if (!initialised.current && c.data_to) {
        initialised.current = true;
        const to = new Date(c.data_to);
        const from = new Date(to); from.setDate(from.getDate() - 29);
        const lo = c.data_from ? new Date(c.data_from) : from;
        setFilters({ date_from: (from < lo ? lo : from).toISOString().slice(0, 10), date_to: c.data_to });
      }
    } catch (e: any) { setConfigError(e.message); }
  }, []);

  useEffect(() => { void loadConfig(); }, [loadConfig, manual]);

  // Poll live status every 7 seconds. The simulation version only changes when data changed.
  useEffect(() => {
    let stop = false;
    const poll = async () => {
      try {
        const s = await get<SimStatus>("/api/live/status");
        if (!stop) { setSim(s); setSimError(null); setLastUpdated(new Date()); }
      } catch (e: any) { if (!stop) setSimError(e.message); }
    };
    void poll();
    const id = window.setInterval(poll, 7000);
    return () => { stop = true; window.clearInterval(id); };
  }, []);

  const simAction = useCallback(async (a: "start" | "pause" | "reset" | "tick") => {
    try { setSim(await send("POST", `/api/simulation/${a}`)); setSimError(null); setLastUpdated(new Date()); if (a === "reset") setManual((m) => m + 1); }
    catch (e: any) { setSimError(e.message); }
  }, []);

  const version = (sim?.version ?? 0) * 1000 + manual;
  const value = useMemo<Ctx>(() => ({
    filters, setFilters, config, configError, machines, products, lines, sim, simError, lastUpdated, version,
    refresh: () => setManual((m) => m + 1), simAction,
  }), [filters, config, configError, machines, products, lines, sim, simError, lastUpdated, version, simAction]);
  return <AppCtx.Provider value={value}>{children}</AppCtx.Provider>;
}
