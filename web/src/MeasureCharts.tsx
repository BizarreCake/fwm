import { Chart } from "./Chart";
import type { TimeControls } from "./time";
import { axisUsd, ticks, usd } from "./util";

export interface MeasureSeries {
  level: (number | null)[];
  transactions: (number | null)[];
  other_change: (number | null)[];
}

interface Props {
  name: string;
  measures: MeasureSeries;
  fill: string;
  time: TimeControls;
}

const OTHER = "var(--muted)";

/** One position over time: its level, and each quarter's change split into transactions vs. valuation. */
export function MeasureCharts({ name, measures, fill, time }: Props) {
  const { periods, start, end, period } = time;
  const level = (i: number) => measures.level[i] ?? 0;
  const tx = (i: number) => measures.transactions[i] ?? 0;
  const other = (i: number) => measures.other_change[i] ?? 0;

  let levelMax = 0;
  let levelMin = 0;
  let changeMin = 0;
  let changeMax = 0;
  for (let i = start; i <= end; i++) {
    levelMax = Math.max(levelMax, level(i));
    levelMin = Math.min(levelMin, level(i));
    changeMax = Math.max(changeMax, Math.max(tx(i), 0) + Math.max(other(i), 0));
    changeMin = Math.min(changeMin, Math.min(tx(i), 0) + Math.min(other(i), 0));
  }
  const levelTicks = ticks(levelMin, levelMax || 1, 3);
  const levelDomain: [number, number] = [Math.min(levelMin, levelTicks[0]), Math.max(levelMax, levelTicks[levelTicks.length - 1])];
  const levelAbs = Math.max(Math.abs(levelDomain[0]), Math.abs(levelDomain[1]));
  const changeTicks = ticks(changeMin, changeMax || 1, 4);
  const changeDomain: [number, number] = [Math.min(changeMin, changeTicks[0]), Math.max(changeMax, changeTicks[changeTicks.length - 1])];
  const changeAbs = Math.max(Math.abs(changeDomain[0]), Math.abs(changeDomain[1]));

  return (
    <div className="detail-charts">
      <figure>
        <figcaption>Amount outstanding</figcaption>
        <Chart
          periods={periods}
          start={start}
          end={end}
          domain={levelDomain}
          yTicks={levelTicks}
          formatY={(v) => axisUsd(v, levelAbs)}
          height={200}
          period={period}
          onPeriod={time.choose}
          ariaLabel={`${name}: amount outstanding over time`}
          tooltip={(i) => (measures.level[i] === null ? [] : [{ key: "level", label: "outstanding", value: usd(level(i)), color: fill }])}
        >
          {({ x, y }) => {
            const points = [];
            for (let i = start; i <= end; i++) points.push(`${x(i)},${y(level(i))}`);
            return (
              <>
                <path d={`M${x(start)},${y(0)} L${points.join(" L")} L${x(end)},${y(0)} Z`} fill={fill} opacity={0.1} />
                <path d={`M${points.join(" L")}`} fill="none" stroke={fill} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
                <circle cx={x(period)} cy={y(level(period))} r={4} fill={fill} stroke="var(--surface)" strokeWidth={2} />
              </>
            );
          }}
        </Chart>
      </figure>
      <figure>
        <figcaption>
          Quarterly change
          <span className="legend">
            <span className="swatch" style={{ background: fill }} /> Net transactions
            <span className="swatch" style={{ background: OTHER }} /> Valuation &amp; other
          </span>
        </figcaption>
        <Chart
          periods={periods}
          start={start}
          end={end}
          domain={changeDomain}
          yTicks={changeTicks}
          formatY={(v) => axisUsd(v, changeAbs)}
          height={200}
          period={period}
          onPeriod={time.choose}
          banded
          ariaLabel={`${name}: quarterly change, split into net transactions and valuation`}
          tooltip={(i) => [
            ...(measures.transactions[i] === null ? [] : [{ key: "tx", label: "net transactions", value: usd(tx(i), true), color: fill }]),
            ...(measures.other_change[i] === null ? [] : [{ key: "other", label: "valuation & other", value: usd(other(i), true), color: OTHER }]),
          ]}
        >
          {({ x, y, step }) => {
            const barWidth = Math.max(1, Math.min(24, step - (step > 6 ? 2 : step > 3 ? 1 : 0)));
            const bars = [];
            for (let i = start; i <= end; i++) {
              let up = 0;
              let down = 0;
              const parts: [number, string][] = [
                [tx(i), fill],
                [other(i), OTHER],
              ];
              for (const [v, c] of parts) {
                if (v === 0) continue;
                const from = v > 0 ? up : down;
                const to = from + v;
                if (v > 0) up = to;
                else down = to;
                bars.push(
                  <rect key={`${i}${c}`} x={x(i) - barWidth / 2} y={y(Math.max(from, to))} width={barWidth} height={Math.max(Math.abs(y(from) - y(to)), 0.5)} fill={c} />,
                );
              }
            }
            return bars;
          }}
        </Chart>
      </figure>
    </div>
  );
}
