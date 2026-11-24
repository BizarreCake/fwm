import { createContext, useContext, type ReactNode } from "react";
import type { ContextView } from "./types";
import { useFetch } from "./useFetch";

const Context = createContext<ContextView | null>(null);

/** Rates, GDP and policy events, fetched once and shared by every chart. Pages work without it. */
export function ContextProvider({ economy, children }: { economy: string; children: ReactNode }) {
  const { data } = useFetch<ContextView>(`/api/economy/${economy}/context`);
  return <Context.Provider value={data}>{children}</Context.Provider>;
}

export function useContextData(): ContextView | null {
  return useContext(Context);
}
