export function fmtNum(v: number | null | undefined, digits = 0): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "n/a";
  return new Intl.NumberFormat("en-IN", { maximumFractionDigits: digits, minimumFractionDigits: digits }).format(v);
}

export function fmtMoney(v: number | null | undefined, currency = "INR", compact = false): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "n/a";
  if (compact) {
    const a = Math.abs(v);
    const sym = currency === "INR" ? "₹" : `${currency} `;
    if (a >= 1e7) return `${sym}${(v / 1e7).toFixed(2)} Cr`;
    if (a >= 1e5) return `${sym}${(v / 1e5).toFixed(2)} L`;
    if (a >= 1e3) return `${sym}${(v / 1e3).toFixed(1)}k`;
    return `${sym}${v.toFixed(0)}`;
  }
  return new Intl.NumberFormat("en-IN", { style: "currency", currency, maximumFractionDigits: 0 }).format(v);
}

export function fmtPct(v: number | null | undefined, digits = 2): string {
  return v === null || v === undefined || Number.isNaN(v) ? "n/a" : `${v.toFixed(digits)}%`;
}

export function fmtValue(v: number | null, unit: string, currency: string): string {
  if (v === null || v === undefined) return "n/a";
  if (unit === currency) return fmtMoney(v, currency, true);
  if (unit === "%") return fmtPct(v);
  return `${fmtNum(v)}${unit && unit !== "units" ? ` ${unit}` : ""}`;
}

/** Direction of a change relative to what is good for the metric. */
export function tone(diff: number | null, better: "higher" | "lower"): "good" | "bad" | "flat" {
  if (diff === null || diff === 0) return "flat";
  return (diff > 0) === (better === "higher") ? "good" : "bad";
}

export function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return "n/a";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" });
}
