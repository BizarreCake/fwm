import { Chart } from "./Chart";
import { useContextData } from "./context";
import type { TimeControls } from "./time";
import type { Mode } from "./types";
import { axisUsd, pct, ticks, usd } from "./util";

export interface StackSeries {
  id: string;
  name: string;
  color: string;
  values: (number | null)[];
}

interface Props {
  series: StackSeries[];
  time: TimeControls;
  mode: Mode;
  selected?: string;
  ariaLabel: string;
}

/** Stacked areas over time, in dollars, as a share of the total, or as a share of GDP. Negative values are drawn as zero. */
export function StackedChart({ series, time, mode, selected, ariaLabel }: Props) {
  const { periods, start, end } = time;
  const at = (s: StackSeries, i: number) => Math.max(0, s.values[i] ?? 0);
  const totalAt = (i: number) => series.reduce((sum, s) => sum + at(s, i), 0) || 1;
  const gdp = useContextData()?.gdp.values;
  // Fall back to dollars if GDP is not available for these quarters.
  if (mode === "gdp" && (!gdp || gdp.length !== periods.length)) mode = "usd";
  const scaleAt = (i: number) => (mode === "usd" ? 1 : mode === "gdp" ? (gdp![i] ?? NaN) : totalAt(i));
  const value = (s: StackSeries, i: number) => at(s, i) / scaleAt(i) || 0;

  let max = 1;
  if (mode !== "share") {
    max = 0;
    for (let i = start; i <= end; i++) max = Math.max(max, series.reduce((sum, s) => sum + value(s, i), 0));
  }
  const yTicks = mode === "share" ? [0, 0.25, 0.5, 0.75, 1] : ticks(0, max, 4);
  const top = mode === "share" ? 1 : Math.max(max, yTicks[yTicks.length - 1]);

  return (
    <Chart
      periods={periods}
      start={start}
      end={end}
      domain={[0, top]}
      yTicks={yTicks}
      formatY={(v) => (mode === "usd" ? axisUsd(v, top) : pct(v, 0))}
      height={300}
      period={time.period}
      onPeriod={time.choose}
      ariaLabel={ariaLabel}
      tooltip={(i) =>
        [...series].reverse().map((s) => ({
          key: s.id,
          label: s.name,
          color: s.color,
          value: mode === "usd" ? usd(s.values[i] ?? 0) : pct(value(s, i)),
        }))
      }
    >
      {({ x, y }) => {
        const base = new Array(end - start + 1).fill(0);
        return series.map((s) => {
          const lower = [...base];
          const upper = lower.map((b, k) => b + value(s, start + k));
          upper.forEach((u, k) => (base[k] = u));
          const forward = upper.map((v, k) => `${x(start + k)},${y(v)}`).join(" L");
          const back = lower.map((v, k) => `${x(start + k)},${y(v)}`).reverse().join(" L");
          return (
            <path
              key={s.id}
              d={`M${forward} L${back} Z`}
              fill={s.color}
              opacity={!selected || selected === s.id ? 1 : 0.55}
              stroke="var(--surface)"
              strokeWidth={1}
            />
          );
        });
      }}
    </Chart>
  );
}
