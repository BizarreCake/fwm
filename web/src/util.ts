import { useEffect, useRef, useState } from "react";

/** Values arrive in USD millions. */
export function usd(millions: number, signed = false): string {
  const abs = Math.abs(millions);
  if (abs < 0.5) return "$0";
  const sign = millions < 0 ? "−" : signed && millions > 0 ? "+" : "";
  let body: string;
  if (abs >= 1e6) body = `${(abs / 1e6).toFixed(abs >= 1e7 ? 1 : 2)}T`;
  else if (abs >= 1e3) body = `${(abs / 1e3).toFixed(abs >= 1e5 ? 0 : 1)}B`;
  else body = `${abs.toFixed(0)}M`;
  return `${sign}$${body}`;
}

export function pct(fraction: number, digits = 1): string {
  return `${(fraction * 100).toFixed(digits)}%`;
}

/** '2026:Q2' -> 'Q2 2026' */
export function periodLabel(period: string): string {
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
  if (millions === 0) return "$0";
  const sign = millions < 0 ? "−" : "";
  const abs = Math.abs(millions);
  if (maxAbs >= 1e6) return `${sign}$${trim(abs / 1e6)}T`;
  if (maxAbs >= 1e3) return `${sign}$${trim(abs / 1e3)}B`;
  return `${sign}$${trim(abs)}M`;
}

function trim(value: number): string {
  return value.toFixed(2).replace(/\.?0+$/, "");
}

/** Indices of the first quarter of years that make sensible x-axis ticks. */
export function yearTicks(periods: string[], start: number, end: number, width: number): number[] {
  const years = (end - start) / 4;
  const maxTicks = Math.max(2, Math.floor(width / 64));
  const step = [1, 2, 5, 10, 20].find((s) => years / s <= maxTicks) ?? 20;
  const out: number[] = [];
  for (let i = start; i <= end; i++) {
    const [year, quarter] = periods[i].split(":");
    if (quarter === "Q1" && Number(year) % step === 0) out.push(i);
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
