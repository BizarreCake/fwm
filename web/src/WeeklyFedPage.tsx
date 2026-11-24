import { useEffect, useState } from "react";
import { Chart } from "./Chart";
import { ModeToggle } from "./ModeToggle";
import { StackedChart } from "./StackedChart";
import { TimeBar, useTimeControls, type Range, type TimeControls } from "./time";
import type { Mode, WeeklyLine, WeeklyView } from "./types";
import { useFetch } from "./useFetch";
import { axisUsd, periodLabel, ticks, usd } from "./util";

type Side = "assets" | "liabilities";

// Colour follows the line, in a fixed order per side; the computed "other" lines are gray.
const SLOT: Record<string, string> = {
  treasuries: "var(--s1)", mbs: "var(--s2)", agency_debt: "var(--s3)", premiums: "var(--s4)", repo: "var(--s5)",
  loans: "var(--s6)", swaps: "var(--s7)", other_assets: "var(--muted)",
  currency: "var(--s1)", reserves: "var(--s2)", reverse_repo: "var(--s3)", tga: "var(--s4)", other_deposits: "var(--s5)",
  remittances: "var(--s6)", capital: "var(--s7)", other_liabilities: "var(--muted)",
};
const HEADLINE = ["reserves", "reverse_repo", "tga"];

function useWeekly() {
  return useFetch<WeeklyView>("/api/economy/us/weekly/fed");
}

/** On the overview: the newest figures in the system, which are weeks old where the accounts are months old. */
export function WeeklyStrip() {
  const { data } = useWeekly();
  if (!data) return null;
  const last = data.periods.length - 1;
  const anchor = data.quarterly.index;
  const lines = data.liabilities.lines.filter((line) => HEADLINE.includes(line.id));
  const tiles = [{ id: "total", name: "Federal Reserve total assets", level: data.assets.total }, ...lines];
  return (
    <section className="card">
      <div className="card-head">
        <h2>Since the quarter ended: the Fed's balance sheet on {periodLabel(data.periods[last])}</h2>
        <a href="#/us/weekly/fed">Weekly balance sheet →</a>
      </div>
      <div className="tiles">
        {tiles.map((tile) => (
          <div key={tile.id} className="tile">
            <div className="muted">{tile.name}</div>
            <div className="tile-value">{usd(tile.level[last])}</div>
            <div className="muted">
              {usd(tile.level[last] - tile.level[anchor], true)} since {periodLabel(data.periods[anchor])}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

export function WeeklyFedPage({ period }: { period?: string }) {
  const { data, error } = useWeekly();
  if (error) {
    return (
      <main className="page">
        <a href="#/">← Overview</a>
        <p>Could not load the weekly balance sheet: {error}</p>
      </main>
    );
  }
  if (!data) return <main className="page"><p className="muted">Loading…</p></main>;
  return <Weekly view={data} period={period} />;
}

function find(lines: WeeklyLine[], id: string): { line: WeeklyLine; top: WeeklyLine } | null {
  for (const top of lines) {
    if (top.id === id) return { line: top, top };
    const child = top.children.find((c) => c.id === id);
    if (child) return { line: child, top };
  }
  return null;
}

function Weekly({ view, period: linked }: { view: WeeklyView; period?: string }) {
  const { periods, quarterly, source, notes } = view;
  const last = periods.length - 1;
  const ranges: Range[] = [
    { label: "1 year", from: periods[Math.max(0, last - 52)] },
    { label: "Since 2020", from: "2020-01-01" },
    { label: "Since 2008", from: "2008-01-01" },
    { label: `Since ${periods[0].slice(0, 4)}`, from: periods[0] },
  ];
  const time = useTimeControls(periods, ranges, 1);
  const week = time.period;
  const show = time.show;
  useEffect(() => {
    if (linked) show(periods.find((p) => p >= linked) ?? linked);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [linked]);

  const [selected, setSelected] = useState("reserves");
  const [side, setSide] = useState<Side>("liabilities");
  const [mode, setMode] = useState<Mode>("usd");

  const found = find(view.liabilities.lines, selected) ?? find(view.assets.lines, selected)!;
  const fill = SLOT[found.top.id];
  const anchor = quarterly.index;
  const afterQuarter = week > anchor;

  const sheet = (name: Side, title: string) => {
    const rows = view[name].lines.flatMap((line) => [{ line, depth: 0 }, ...line.children.map((child) => ({ line: child, depth: 1 }))]);
    return (
      <div className="scroll-x">
        <table className="table holders weekly">
          <thead>
            <tr>
              <th>{title}</th>
              <th className="num">Amount</th>
              <th className="num">Week</th>
              <th className="num">{afterQuarter ? `Since ${periodLabel(periods[anchor])}` : "Year"}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(({ line, depth }) => {
              const on = line.id === selected;
              const base = afterQuarter ? anchor : Math.max(0, week - 52);
              return (
                <tr
                  key={line.id}
                  className={on ? "selected" : ""}
                  onClick={() => {
                    setSelected(line.id);
                    setSide(name);
                  }}
                >
                  <td style={{ paddingLeft: 8 + depth * 20 }}>
                    <button className="row-button" aria-pressed={on}>
                      {depth === 0 && <span className="swatch" style={{ background: SLOT[line.id] }} />}
                      {line.name}
                    </button>
                  </td>
                  <td className="num">{usd(line.level[week])}</td>
                  <td className="num">{week > 0 ? usd(line.level[week] - line.level[week - 1], true) : "–"}</td>
                  <td className="num">{usd(line.level[week] - line.level[base], true)}</td>
                </tr>
              );
            })}
          </tbody>
          <tfoot>
            <tr>
              <td>{name === "assets" ? "Total assets" : "Total liabilities and capital"}</td>
              <td className="num">{usd(view[name].total[week])}</td>
              <td className="num">{week > 0 ? usd(view[name].total[week] - view[name].total[week - 1], true) : "–"}</td>
              <td className="num">{usd(view[name].total[week] - view[name].total[afterQuarter ? anchor : Math.max(0, week - 52)], true)}</td>
            </tr>
          </tfoot>
        </table>
      </div>
    );
  };

  const stack = view[side].lines.map((line) => ({ id: line.id, name: line.name, color: SLOT[line.id], values: line.level }));

  return (
    <main className="page">
      <header className="header">
        <div>
          <a className="back" href="#/">
            ← Overview
          </a>
          <h1>Federal Reserve, weekly</h1>
          <p className="muted">
            Its balance sheet every Wednesday, through {periodLabel(periods[last])}. The quarterly accounts end in{" "}
            {periodLabel(quarterly.period)}:{" "}
            <a href={`#/us/sector/${quarterly.sector_id}`}>Federal Reserve in the quarterly accounts →</a>
          </p>
        </div>
        <div className="hero">
          <div className="hero-value">{usd(view.assets.total[week])}</div>
          <div className="muted">total assets, {periodLabel(periods[week])}</div>
        </div>
      </header>

      <TimeBar time={time} />

      <section className="card tables">
        {sheet("assets", "Assets")}
        {sheet("liabilities", "Liabilities and capital")}
      </section>

      <section className="card">
        <div className="card-head">
          <h2>Composition over time</h2>
          <div className="controls">
            <div className="segmented" role="group" aria-label="Side of the balance sheet">
              <button aria-pressed={side === "assets"} onClick={() => setSide("assets")}>
                Assets
              </button>
              <button aria-pressed={side === "liabilities"} onClick={() => setSide("liabilities")}>
                Liabilities
              </button>
            </div>
            <ModeToggle mode={mode} onChange={setMode} gdp={false} />
          </div>
        </div>
        <StackedChart
          series={stack}
          time={time}
          mode={mode}
          selected={stack.some((s) => s.id === found.top.id) ? found.top.id : undefined}
          ariaLabel={`Federal Reserve ${side} by line, weekly`}
          events={view.events}
        />
        <div className="legend-row">
          {stack.map((s) => (
            <button key={s.id} className="row-button" aria-pressed={s.id === selected} onClick={() => setSelected(s.id)}>
              <span className="swatch" style={{ background: s.color }} />
              {s.name}
            </button>
          ))}
        </div>
        {side === "liabilities" && <p className="muted small">Negative amounts (deferred remittances) are not drawn in the stack.</p>}
      </section>

      <section className="card">
        <div className="card-head">
          <h2>
            <span className="swatch" style={{ background: fill }} />
            {found.line.name}
          </h2>
          <p className="muted">
            {found.line.series.length ? `H.4.1 series ${found.line.series.join(", ")}` : "Computed: the total less the named lines"}
          </p>
        </div>
        <LineCharts line={found.line} fill={fill} time={time} events={view.events} />
        {view.events
          .filter((event) => event.index === week)
          .map((event) => (
            <p key={event.date} className="events">
              <span className="event-date">{event.date}</span> <strong>{event.title}.</strong> {event.detail} <a href={event.url}>Press release</a>
            </p>
          ))}
      </section>

      <footer className="footer muted">
        <p>
          Source: <a href={source.url}>{source.name}</a>. Latest week {periodLabel(source.latest)}.
        </p>
        <p>{notes.basis}</p>
        <p>{notes.other}</p>
        <p>{notes.counterparties}</p>
      </footer>
    </main>
  );
}

function LineCharts({ line, fill, time, events }: { line: WeeklyLine; fill: string; time: TimeControls; events: WeeklyView["events"] }) {
  const { periods, start, end, period } = time;
  const change = (i: number) => (i > 0 ? line.level[i] - line.level[i - 1] : 0);
  let lo = 0, hi = 0, changeLo = 0, changeHi = 0;
  for (let i = start; i <= end; i++) {
    lo = Math.min(lo, line.level[i]);
    hi = Math.max(hi, line.level[i]);
    changeLo = Math.min(changeLo, change(i));
    changeHi = Math.max(changeHi, change(i));
  }
  const levelTicks = ticks(lo, hi || 1, 3);
  const levelDomain: [number, number] = [Math.min(lo, levelTicks[0]), Math.max(hi, levelTicks[levelTicks.length - 1])];
  const changeTicks = ticks(changeLo, changeHi || 1, 4);
  const changeDomain: [number, number] = [Math.min(changeLo, changeTicks[0]), Math.max(changeHi, changeTicks[changeTicks.length - 1])];
  const abs = (d: [number, number]) => Math.max(Math.abs(d[0]), Math.abs(d[1]));

  return (
    <div className="detail-charts">
      <figure>
        <figcaption>Amount</figcaption>
        <Chart
          periods={periods}
          start={start}
          end={end}
          domain={levelDomain}
          yTicks={levelTicks}
          formatY={(v) => axisUsd(v, abs(levelDomain))}
          height={200}
          period={period}
          onPeriod={time.choose}
          events={events}
          ariaLabel={`${line.name}: amount each week`}
          tooltip={(i) => [{ key: "level", label: "amount", value: usd(line.level[i]), color: fill }]}
        >
          {({ x, y }) => {
            const points = [];
            for (let i = start; i <= end; i++) points.push(`${x(i)},${y(line.level[i])}`);
            return (
              <>
                <path d={`M${x(start)},${y(0)} L${points.join(" L")} L${x(end)},${y(0)} Z`} fill={fill} opacity={0.1} />
                <path d={`M${points.join(" L")}`} fill="none" stroke={fill} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
                <circle cx={x(period)} cy={y(line.level[period])} r={4} fill={fill} stroke="var(--surface)" strokeWidth={2} />
              </>
            );
          }}
        </Chart>
      </figure>
      <figure>
        <figcaption>Change from the week before</figcaption>
        <Chart
          periods={periods}
          start={start}
          end={end}
          domain={changeDomain}
          yTicks={changeTicks}
          formatY={(v) => axisUsd(v, abs(changeDomain))}
          height={200}
          period={period}
          onPeriod={time.choose}
          banded
          events={events}
          ariaLabel={`${line.name}: change from the week before`}
          tooltip={(i) => [{ key: "change", label: "change in the week", value: usd(change(i), true), color: fill }]}
        >
          {({ x, y, step }) => {
            const width = Math.max(1, Math.min(16, step - (step > 4 ? 1 : 0)));
            const bars = [];
            for (let i = start; i <= end; i++) {
              const v = change(i);
              if (v === 0) continue;
              bars.push(<rect key={i} x={x(i) - width / 2} y={y(Math.max(v, 0))} width={width} height={Math.max(Math.abs(y(v) - y(0)), 0.5)} fill={fill} />);
            }
            return bars;
          }}
        </Chart>
      </figure>
    </div>
  );
}
