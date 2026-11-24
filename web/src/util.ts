import { useEffect, useRef, useState } from "react";

/** Values arrive in USD millions. */
// The economy whose pages are showing. Set by the router before a page renders; it decides the currency
// symbol, the API paths and the link prefix, so page components need not pass it around.
const ECONOMIES: Record<string, { name: string; symbol: string; currency: string }> = {
  us: { name: "United States", symbol: "$", currency: "Dollars" },
  ea: { name: "Euro area", symbol: "€", currency: "Euros" },
};
let ECONOMY = "us";

export function setEconomy(id: string): void {
  ECONOMY = ECONOMIES[id] ? id : "us";
}
export const economy = () => ECONOMY;
export const economyName = () => ECONOMIES[ECONOMY].name;
export const currencyName = () => ECONOMIES[ECONOMY].currency;
export const economies = () => Object.entries(ECONOMIES).map(([id, e]) => ({ id, name: e.name }));
const symbol = () => ECONOMIES[ECONOMY].symbol;
/** Link prefix for the current economy's pages, e.g. '#/ea'. */
export const base = () => `#/${ECONOMY}`;
/** The current economy's overview. */
export const home = () => (ECONOMY === "us" ? "#/" : `#/${ECONOMY}`);
/** API path for the current economy, e.g. api('sectors') -> '/api/economy/ea/sectors'. */
export const api = (path: string) => `/api/economy/${ECONOMY}/${path}`;

/** An amount in millions of the current economy's currency. (Named for the first economy; it is not always dollars.) */
export function usd(millions: number, signed = false): string {
  const abs = Math.abs(millions);
  if (abs < 0.5) return `${symbol()}0`;
  const sign = millions < 0 ? "−" : signed && millions > 0 ? "+" : "";
  let body: string;
  if (abs >= 1e6) body = `${(abs / 1e6).toFixed(abs >= 1e7 ? 1 : 2)}T`;
  else if (abs >= 1e3) body = `${(abs / 1e3).toFixed(abs >= 1e5 ? 0 : 1)}B`;
  else body = `${abs.toFixed(0)}M`;
  return `${sign}${symbol()}${body}`;
}

export function pct(fraction: number, digits = 1): string {
  return `${(fraction * 100).toFixed(digits)}%`;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** '2026:Q2' -> 'Q2 2026'; '2026-11-18' -> 'Nov 18, 2026' */
export function periodLabel(period: string): string {
  const date = period.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (date) return `${MONTHS[Number(date[2]) - 1]} ${Number(date[3])}, ${date[1]}`;
  const month = period.match(/^(\d{4})-(\d{2})$/);
  if (month) return `${MONTHS[Number(month[2]) - 1]} ${month[1]}`;
  const [year, quarter] = period.split(":");
  return `${quarter} ${year}`;
}

export function color(groupId: string): string {
  return `var(--c-${groupId})`;
}

/** Round tick values covering [min, max], always including zero when it is in range. */
export function ticks(min: number, max: number, target = 4): number[] {
  const span = max - min || 1;
  const raw = span / target;
  const pow = Math.pow(10, Math.floor(Math.log10(raw)));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * pow).find((s) => s >= raw) ?? 10 * pow;
  const out: number[] = [];
  for (let v = Math.ceil(min / step) * step; v <= max + step * 1e-9; v += step) {
    out.push(Math.abs(v) < step * 1e-9 ? 0 : v);
  }
  return out;
}

/** Tick label for an axis in USD millions; one style across the axis. */
export function axisUsd(millions: number, maxAbs: number): string {
  if (millions === 0) return `${symbol()}0`;
  const sign = millions < 0 ? "−" : "";
  const abs = Math.abs(millions);
  if (maxAbs >= 1e6) return `${sign}${symbol()}${trim(abs / 1e6)}T`;
  if (maxAbs >= 1e3) return `${sign}${symbol()}${trim(abs / 1e3)}B`;
  return `${sign}${symbol()}${trim(abs)}M`;
}

function trim(value: number): string {
  return value.toFixed(2).replace(/\.?0+$/, "");
}

/** Indices of the first period of years that make sensible x-axis ticks. Periods are quarters or dates. */
export function yearTicks(periods: string[], start: number, end: number, width: number): number[] {
  const year = (i: number) => periods[i].slice(0, 4);
  const years = Number(year(end)) - Number(year(start));
  const maxTicks = Math.max(2, Math.floor(width / 64));
  const step = [1, 2, 5, 10, 20].find((s) => years / s <= maxTicks) ?? 20;
  const out: number[] = [];
  for (let i = start; i <= end; i++) {
    const first = i === 0 ? /(:Q1|-01-0\d|^\d{4}-01)$/.test(periods[i]) : year(i) !== year(i - 1);
    if (first && Number(year(i)) % step === 0) out.push(i);
  }
  return out;
}

export function useWidth<T extends HTMLElement>(): [React.RefObject<T | null>, number] {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.floor(entry.contentRect.width)));
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  return [ref, width];
}

/** 'China, Mainland' -> 'china-mainland'. Must match fwm.countries.slug. */
export function slug(name: string): string {
  return name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
}
