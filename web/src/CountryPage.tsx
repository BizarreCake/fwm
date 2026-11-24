import { useEffect, useState } from "react";
import { Chart } from "./Chart";
import { CountryLinksCard } from "./CountryLinks";
import { ModeToggle } from "./ModeToggle";
import { StackedChart } from "./StackedChart";
import { TimeBar, useTimeControls, type Range, type TimeControls } from "./time";
import type { CountryLine, CountrySide, CountrySummary, CountryView, Mode } from "./types";
import { useFetch } from "./useFetch";
import { axisUsd, periodLabel, ticks, usd } from "./util";

type Direction = "holds_us" | "held_by_us";

// Colour follows the kind of security, the same in both directions where the kinds correspond.
const LINE_COLOR: Record<string, string> = {
  treasuries: "var(--s1)", agency: "var(--s3)", corporate: "var(--s4)", equities: "var(--s2)",
  us_foreign_government_bonds: "var(--s1)", us_foreign_corporate_bonds: "var(--s4)", us_foreign_equities: "var(--s2)",
};
const SHORT_LIST = 12;
const money = (v: number | null | undefined, signed = false) => (v == null ? "n/a" : usd(v, signed));

function trailing(values: (number | null)[], i: number): number | null {
  if (i < 11) return null;
  let sum = 0;
  for (let k = i - 11; k <= i; k++) {
    const v = values[k];
    if (v == null) return null;
    sum += v;
  }
  return sum;
}

/** On the overview: countries as counterparties of the US. */
export function CountriesCard() {
  const { data } = useFetch<CountrySummary[]>("/api/countries");
  const [all, setAll] = useState(false);
  if (!data || data.length === 0) return null;
  const countries = data.filter((c) => c.kind === "country");
  const shown = all ? countries : countries.slice(0, SHORT_LIST);
  return (
    <section className="card">
      <div className="card-head">
        <h2>Countries, as seen from the US</h2>
        <p className="muted">Securities only. Each country's own accounts are not loaded.</p>
      </div>
      <div className="scroll-x">
        <table className="table countries">
          <thead>
            <tr>
              <th>Country</th>
              <th className="num">Holds in US securities</th>
              <th className="num">US residents hold of its securities</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((c) => (
              <tr key={c.id}>
                <td>
                  <a href={`#/country/${c.id}`}>{c.name}</a>
                </td>
                <td className="num">{money(c.holds_us)}</td>
                <td className="num">{money(c.held_by_us)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <button className="link-button" onClick={() => setAll(!all)}>
        {all ? `Show the top ${SHORT_LIST}` : `Show all ${countries.length} countries`}
      </button>
      <p className="muted small">
        Groups: {data.filter((c) => c.kind === "group").map((c, i) => (
          <span key={c.id}>
            {i > 0 && ", "}
            <a href={`#/country/${c.id}`}>{c.name}</a>
          </span>
        ))}
        . A country is where US securities are held in custody, so financial centres rank high.
      </p>
    </section>
  );
}

export function CountryPage({ countryId, period }: { countryId: string; period?: string }) {
  const { data, error } = useFetch<CountryView>(`/api/countries/${countryId}`);
  if (error) {
    return (
      <main className="page">
        <a href="#/">← Overview</a>
        <p>Could not load this country: {error}</p>
      </main>
    );
  }
  if (!data) return <main className="page"><p className="muted">Loading…</p></main>;
  return <Country view={data} period={period} />;
}

function Country({ view, period: linked }: { view: CountryView; period?: string }) {
  const { periods, notes, source } = view;
  const last = periods.length - 1;
  const ranges: Range[] = [
    { label: "2 years", from: periods[Math.max(0, last - 24)] },
    { label: `Since ${periods[0].slice(0, 4)}`, from: periods[0] },
  ];
  const time = useTimeControls(periods, ranges, 1);
  const month = time.period;
  const show = time.show;
  useEffect(() => {
    if (linked) show(linked.slice(0, 7));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [linked]);
  const countries = useFetch<CountrySummary[]>("/api/countries").data;
  const first: Direction = view.holds_us.lines.length ? "holds_us" : "held_by_us";
  const [direction, setDirection] = useState<Direction>(first);
  const [selected, setSelected] = useState(view[first].lines[0].id);
  const [mode, setMode] = useState<Mode>("usd");

  const side = view[direction];
  const line = side.lines.find((l) => l.id === selected) ?? view.holds_us.lines.find((l) => l.id === selected) ??
    view.held_by_us.lines.find((l) => l.id === selected) ?? side.lines[0];
  const yearAgo = month >= 12 ? month - 12 : null;
  const holds = view.holds_us.total[month];
  const held = view.held_by_us.total[month];

  const table = (name: Direction, title: string, sideData: CountrySide) => (
    <div className="scroll-x">
      <table className="table holders bilateral">
        <thead>
          <tr>
            <th>{title}</th>
            <th className="num">Amount</th>
            <th className="num">Share of all countries</th>
            <th className="num">Change, 12 months</th>
            <th className="num">Net purchases, 12 months</th>
          </tr>
        </thead>
        <tbody>
          {sideData.lines.length === 0 && (
            <tr>
              <td colSpan={5} className="muted">Not published for {view.name}.</td>
            </tr>
          )}
          {sideData.lines.map((l) => {
            const on = l.id === line.id;
            const level = l.total[month];
            const before = yearAgo != null ? l.total[yearAgo] : null;
            const everyone = l.all_countries[month];
            return (
              <tr key={l.id} className={on ? "selected" : ""} onClick={() => { setSelected(l.id); setDirection(name); }}>
                <td>
                  <button className="row-button" aria-pressed={on}>
                    <span className="swatch" style={{ background: LINE_COLOR[l.id] }} />
                    {l.name}
                  </button>
                </td>
                <td className="num">{money(level)}</td>
                <td className="num">{level != null && everyone ? `${((level / everyone) * 100).toFixed(1)}%` : "n/a"}</td>
                <td className="num">{level != null && before != null ? usd(level - before, true) : "n/a"}</td>
                <td className="num">{money(trailing(l.total_net, month), true)}</td>
              </tr>
            );
          })}
        </tbody>
        {sideData.lines.length > 1 && (
          <tfoot>
            <tr>
              <td>Total published</td>
              <td className="num">{money(sideData.total[month])}</td>
              <td />
              <td className="num">{yearAgo != null && sideData.total[month] != null && sideData.total[yearAgo] != null ? usd(sideData.total[month]! - sideData.total[yearAgo]!, true) : "n/a"}</td>
              <td className="num">{money(trailing(sideData.total_net, month), true)}</td>
            </tr>
          </tfoot>
        )}
      </table>
    </div>
  );

  const stack = side.lines.map((l) => ({ id: l.id, name: l.name, color: LINE_COLOR[l.id], values: l.total }));

  return (
    <main className="page">
      <header className="header">
        <div>
          <a className="back" href="#/">
            ← Overview
          </a>
          <h1>{view.name} and the United States</h1>
          <p className="muted">
            {view.kind === "group" ? "A group of countries" : "A country"} seen from the US: what it holds in US securities, and what US residents hold of
            its securities.{" "}
            {countries && (
              <select aria-label="Switch country" value={view.id} onChange={(e) => (window.location.hash = `#/country/${e.target.value}`)}>
                {[...countries].sort((a, b) => a.name.localeCompare(b.name)).map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
            )}
          </p>
        </div>
      </header>

      <p className="callout">
        {notes.scope}
        {view.has_links && <> Its positions with every other country, from the IMF and BIS, are <a href="#links" onClick={(e) => { e.preventDefault(); document.getElementById("links")?.scrollIntoView(); }}>further down</a>.</>}
      </p>

      <TimeBar time={time} />

      <section className="card">
        <div className="tiles">
          <div className="tile">
            <div className="muted">{view.name} holds in US securities</div>
            <div className="tile-value">{money(holds)}</div>
            <div className="muted">{money(trailing(view.holds_us.total_net, month), true)} net purchases, 12 months</div>
          </div>
          <div className="tile">
            <div className="muted">US residents hold of its securities</div>
            <div className="tile-value">{money(held)}</div>
            <div className="muted">{money(trailing(view.held_by_us.total_net, month), true)} net purchases, 12 months</div>
          </div>
          <div className="tile">
            <div className="muted">Difference</div>
            <div className="tile-value">{holds != null && held != null ? usd(holds - held, true) : "n/a"}</div>
            <div className="muted">{periodLabel(periods[month])}; securities only, counted differently each way</div>
          </div>
        </div>
      </section>

      <section className="card">
        {table("holds_us", `US securities held in ${view.name}`, view.holds_us)}
        <p className="muted small">{notes.custody}</p>
      </section>

      <section className="card">
        {table("held_by_us", `${view.name}'s securities held by US residents`, view.held_by_us)}
        <p className="muted small">{notes.outward}</p>
      </section>

      {side.lines.length > 0 && (
        <section className="card">
          <div className="card-head">
            <h2>Over time</h2>
            <div className="controls">
              <div className="segmented" role="group" aria-label="Direction">
                <button aria-pressed={direction === "holds_us"} disabled={!view.holds_us.lines.length} onClick={() => setDirection("holds_us")}>
                  Its US securities
                </button>
                <button aria-pressed={direction === "held_by_us"} disabled={!view.held_by_us.lines.length} onClick={() => setDirection("held_by_us")}>
                  US holdings of its securities
                </button>
              </div>
              <ModeToggle mode={mode} onChange={setMode} gdp={false} />
            </div>
          </div>
          <StackedChart
            series={stack}
            time={time}
            mode={mode}
            selected={stack.some((s) => s.id === line.id) ? line.id : undefined}
            ariaLabel={direction === "holds_us" ? `US securities held in ${view.name}, monthly` : `${view.name}'s securities held by US residents, monthly`}
            events={[]}
          />
          <div className="legend-row">
            {stack.map((s) => (
              <button key={s.id} className="row-button" aria-pressed={s.id === line.id} onClick={() => setSelected(s.id)}>
                <span className="swatch" style={{ background: s.color }} />
                {s.name}
              </button>
            ))}
          </div>
        </section>
      )}

      <section className="card">
        <div className="card-head">
          <h2>
            <span className="swatch" style={{ background: LINE_COLOR[line.id] }} />
            {line.name}
          </h2>
          <p className="muted">
            {line.rank != null ? `Rank ${line.rank} of ${line.ranked_among} countries in ${periodLabel(periods[last])}` : ""}
            {line.page && (
              <>
                {line.rank != null ? " · " : ""}
                <a href={line.page}>All countries →</a>
              </>
            )}
          </p>
        </div>
        <LineCharts line={line} view={view} time={time} />
        <p className="muted small">{line.scope}</p>
      </section>

      {view.has_links && <CountryLinksCard key={view.id} countryId={view.id} name={view.name} />}

      <footer className="footer muted">
        <p>
          Source: <a href={source.url}>{source.name}</a>. Latest month {periodLabel(source.latest)}.
        </p>
        <p>{notes.coverage}</p>
        <p>{notes.history}</p>
      </footer>
    </main>
  );
}

function LineCharts({ line, view, time }: { line: CountryLine; view: CountryView; time: TimeControls }) {
  const { periods, start, end, period } = time;
  const fill = LINE_COLOR[line.id];
  let hi = 0, flowLo = 0, flowHi = 0;
  for (let i = start; i <= end; i++) {
    hi = Math.max(hi, line.total[i] ?? 0);
    const net = line.total_net[i];
    if (net != null) {
      flowLo = Math.min(flowLo, net);
      flowHi = Math.max(flowHi, net);
    }
  }
  const levelTicks = ticks(0, hi || 1, 3);
  const levelDomain: [number, number] = [0, Math.max(hi, levelTicks[levelTicks.length - 1])];
  const flowTicks = ticks(flowLo, flowHi || 1, 4);
  const flowDomain: [number, number] = [Math.min(flowLo, flowTicks[0]), Math.max(flowHi, flowTicks[flowTicks.length - 1])];
  const abs = (d: [number, number]) => Math.max(Math.abs(d[0]), Math.abs(d[1]));
  return (
    <div className="detail-charts">
      <figure>
        <figcaption>Holdings</figcaption>
        <Chart
          periods={periods} start={start} end={end} domain={levelDomain} yTicks={levelTicks}
          formatY={(v) => axisUsd(v, abs(levelDomain))} height={200} period={period} onPeriod={time.choose} events={[]}
          ariaLabel={`${view.name}, ${line.name}: holdings each month`}
          tooltip={(i) => [{ key: "total", label: "holdings", value: money(line.total[i]), color: fill }]}
        >
          {({ x, y }) => {
            const points = [];
            for (let i = start; i <= end; i++) if (line.total[i] != null) points.push(`${x(i)},${y(line.total[i]!)}`);
            if (!points.length) return null;
            return (
              <>
                <path d={`M${points.join(" L")}`} fill="none" stroke={fill} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
                {line.total[period] != null && <circle cx={x(period)} cy={y(line.total[period]!)} r={4} fill={fill} stroke="var(--surface)" strokeWidth={2} />}
              </>
            );
          }}
        </Chart>
      </figure>
      <figure>
        <figcaption>Net purchases each month</figcaption>
        <Chart
          periods={periods} start={start} end={end} domain={flowDomain} yTicks={flowTicks}
          formatY={(v) => axisUsd(v, abs(flowDomain))} height={200} period={period} onPeriod={time.choose} banded events={[]}
          ariaLabel={`${view.name}, ${line.name}: net purchases each month`}
          tooltip={(i) => [
            { key: "net", label: "net purchases", value: money(line.total_net[i], true), color: fill },
            { key: "valuation", label: "valuation", value: money(line.long_term_valuation[i], true) },
          ]}
        >
          {({ x, y, step }) => {
            const width = Math.max(1, Math.min(16, step - 2));
            const bars = [];
            for (let i = start; i <= end; i++) {
              const v = line.total_net[i];
              if (v == null || v === 0) continue;
              bars.push(<rect key={i} x={x(i) - width / 2} y={y(Math.max(v, 0))} width={width} height={Math.max(Math.abs(y(v) - y(0)), 0.5)} fill={fill} />);
            }
            return bars;
          }}
        </Chart>
      </figure>
    </div>
  );
}
