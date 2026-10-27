export type Row = Record<string, any>;

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export interface Filters {
  date_from?: string;
  date_to?: string;
  line_id?: number;
  machine_id?: number;
  product_id?: number;
  shift?: "A" | "B" | "C";
}

export interface KpiCard {
  key: string;
  label: string;
  value: number | null;
  previous: number | null;
  unit: string;
  abs_diff: number | null;
  pct_diff: number | null;
  better: "higher" | "lower";
  definition_key: string | null;
}

export interface AppConfig {
  data_label: string;
  currency: string;
  data_from: string | null;
  data_to: string | null;
  production_records: number;
  last_import_at: string | null;
  database: string;
  assumptions: Record<string, number>;
  warning: string;
}

export interface SimStatus {
  mode: string;
  running: boolean;
  ticks: number;
  simulated_clock: string | null;
  last_tick_at: string | null;
  simulated_rows: number;
  retention_limit: number;
  poll_seconds: number;
  version: number;
  error: string | null;
  note: string;
  machines?: Row[];
  recent_events?: Row[];
}

export function qs(params: Record<string, unknown> = {}): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") p.set(k, String(v));
  const s = p.toString();
  return s ? `?${s}` : "";
}

async function parse(res: Response) {
  const text = await res.text();
  let body: any = null;
  try { body = text ? JSON.parse(text) : null; } catch { body = text; }
  if (!res.ok) {
    const detail = body && typeof body === "object" ? body.detail : body;
    const msg = Array.isArray(detail) ? detail.map((d: any) => `${(d.loc || []).slice(1).join(".")}: ${d.msg}`).join("; ") : String(detail || res.statusText);
    throw new ApiError(res.status, msg);
  }
  return body;
}

export async function get<T = any>(path: string, params?: Record<string, unknown>, signal?: AbortSignal): Promise<T> {
  let res: Response;
  try { res = await fetch(`${path}${qs(params)}`, { signal }); }
  catch (e: any) { if (e?.name === "AbortError") throw e; throw new ApiError(0, "Cannot reach the API. Is the backend running?"); }
  return parse(res);
}

export async function send<T = any>(method: "POST" | "PATCH" | "DELETE", path: string, body?: unknown, params?: Record<string, unknown>): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${path}${qs(params)}`, { method, headers: body ? { "Content-Type": "application/json" } : undefined, body: body ? JSON.stringify(body) : undefined });
  } catch { throw new ApiError(0, "Cannot reach the API. Is the backend running?"); }
  return parse(res);
}

export async function upload<T = any>(path: string, form: FormData): Promise<T> {
  let res: Response;
  try { res = await fetch(path, { method: "POST", body: form }); } catch { throw new ApiError(0, "Cannot reach the API. Is the backend running?"); }
  return parse(res);
}

export function downloadUrl(path: string, params: Record<string, unknown> = {}): string {
  return `${path}${qs(params)}`;
}
