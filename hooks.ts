import { useEffect, useState } from "react";
import { ApiError, get } from "./api";
import { useApp } from "./state";

export interface Result<T> { data: T | null; loading: boolean; error: string | null }

/** Fetches `path` with the global filters (and extra params). Refetches when filters or the data version change. */
export function useApi<T = any>(path: string, extra: Record<string, unknown> = {}, opts: { filtered?: boolean } = {}): Result<T> {
  const { filters, version, config } = useApp();
  const [state, setState] = useState<Result<T>>({ data: null, loading: true, error: null });
  const filtered = opts.filtered ?? true;
  const key = JSON.stringify([path, filtered ? filters : {}, extra, version]);
  const ready = !filtered || (config !== null && filters.date_from !== undefined) || (config !== null && config.data_to === null);

  useEffect(() => {
    if (!ready) return;
    const ctl = new AbortController();
    setState((s) => ({ ...s, loading: true, error: null }));
    get<T>(path, { ...(filtered ? filters : {}), ...extra }, ctl.signal)
      .then((data) => setState({ data, loading: false, error: null }))
      .catch((e) => { if (e?.name !== "AbortError") setState((s) => ({ data: s.data, loading: false, error: e instanceof ApiError ? e.message : String(e) })); });
    return () => ctl.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, ready]);
  return state;
}
