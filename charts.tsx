import { Bar, BarChart, CartesianGrid, ComposedChart, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis, Area, AreaChart } from "recharts";
import type { Row } from "../api";
import { fmtMoney, fmtNum } from "../format";
import { EmptyState } from "./ui";

export const COLORS = ["#2563eb", "#d97706", "#059669", "#dc2626", "#7c3aed", "#0891b2"];

export interface Series { key: string; label: string; color?: string; kind?: "line" | "bar" | "area"; money?: boolean; digits?: number }

function fmtTick(v: any, money: boolean, currency: string) {
  if (typeof v !== "number") return String(v);
  return money ? fmtMoney(v, currency, true) : Math.abs(v) >= 1000 ? fmtNum(v / 1000, 1) + "k" : fmtNum(v, Math.abs(v) < 10 ? 2 : 0);
}

export function TimeChart({ data, xKey = "bucket", series, height = 240, currency = "INR", stacked = false }: { data: Row[]; xKey?: string; series: Series[]; height?: number; currency?: string; stacked?: boolean }) {
  if (!data?.length) return <EmptyState />;
  const money = series.every((s) => s.money);
  const hasBar = series.some((s) => s.kind === "bar");
  const Chart: any = hasBar ? ComposedChart : series.every((s) => s.kind === "area") ? AreaChart : LineChart;
  return (
    <div role="img" aria-label={`Chart of ${series.map((s) => s.label).join(", ")} over time`}>
      <ResponsiveContainer width="100%" height={height}>
        <Chart data={data} margin={{ left: 0, right: 8, top: 4, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
          <XAxis dataKey={xKey} tick={{ fontSize: 11 }} tickFormatter={(v) => String(v).slice(5)} minTickGap={24} />
          <YAxis tick={{ fontSize: 11 }} width={money ? 68 : 52} tickFormatter={(v) => fmtTick(v, money, currency)} />
          <Tooltip formatter={(v: any, n: any) => { const s = series.find((x) => x.label === n); return s?.money ? fmtMoney(v, currency) : fmtNum(v, s?.digits ?? 2); }} />
          {series.length > 1 && <Legend wrapperStyle={{ fontSize: 12 }} />}
          {series.map((s, i) => {
            const color = s.color ?? COLORS[i % COLORS.length];
            if (s.kind === "bar") return <Bar key={s.key} dataKey={s.key} name={s.label} fill={color} stackId={stacked ? "a" : undefined} />;
            if (s.kind === "area") return <Area key={s.key} type="monotone" dataKey={s.key} name={s.label} stroke={color} fill={color} fillOpacity={0.15} stackId={stacked ? "a" : undefined} />;
            return <Line key={s.key} type="monotone" dataKey={s.key} name={s.label} stroke={color} strokeWidth={2} dot={false} connectNulls />;
          })}
        </Chart>
      </ResponsiveContainer>
    </div>
  );
}

export function BarsChart({ data, labelKey, series, height = 240, horizontal = false, currency = "INR", stacked = false }: { data: Row[]; labelKey: string; series: Series[]; height?: number; horizontal?: boolean; currency?: string; stacked?: boolean }) {
  if (!data?.length) return <EmptyState />;
  const money = series.every((s) => s.money);
  return (
    <div role="img" aria-label={`Bar chart of ${series.map((s) => s.label).join(", ")} by ${labelKey}`}>
      <ResponsiveContainer width="100%" height={height}>
        <BarChart data={data} layout={horizontal ? "vertical" : "horizontal"} margin={{ left: horizontal ? 24 : 0, right: 8, top: 4, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
          {horizontal ? (
            <>
              <XAxis type="number" tick={{ fontSize: 11 }} tickFormatter={(v) => fmtTick(v, money, currency)} />
              <YAxis type="category" dataKey={labelKey} tick={{ fontSize: 11 }} width={90} />
            </>
          ) : (
            <>
              <XAxis dataKey={labelKey} tick={{ fontSize: 11 }} interval={0} />
              <YAxis tick={{ fontSize: 11 }} width={money ? 68 : 52} tickFormatter={(v) => fmtTick(v, money, currency)} />
            </>
          )}
          <Tooltip formatter={(v: any, n: any) => { const s = series.find((x) => x.label === n); return s?.money ? fmtMoney(v, currency) : fmtNum(v, s?.digits ?? 2); }} />
          {series.length > 1 && <Legend wrapperStyle={{ fontSize: 12 }} />}
          {series.map((s, i) => <Bar key={s.key} dataKey={s.key} name={s.label} fill={s.color ?? COLORS[i % COLORS.length]} stackId={stacked ? "a" : undefined} radius={[2, 2, 0, 0]} />)}
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
