import { useEffect, useState } from "react";

export function useFetch<T>(url: string): { data: T | null; error: string | null } {
  const [state, setState] = useState<{ url: string; data: T | null; error: string | null }>({ url, data: null, error: null });
  useEffect(() => {
    let cancelled = false;
    fetch(url)
      .then(async (response) => {
        if (!response.ok) throw new Error((await response.json().catch(() => null))?.detail ?? response.statusText);
        return response.json();
      })
      .then((data: T) => !cancelled && setState({ url, data, error: null }))
      .catch((e) => !cancelled && setState({ url, data: null, error: String(e.message ?? e) }));
    return () => {
      cancelled = true;
    };
  }, [url]);
  return state.url === url ? state : { data: null, error: null };
}
