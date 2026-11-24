import { useEffect, useMemo, useState } from "react";
import { Chart } from "./Chart";
import { ModeToggle } from "./ModeToggle";
import { StackedChart } from "./StackedChart";
import { TimeBar, useTimeControls, type Range, type TimeControls } from "./time";
import type { ForeignHolder, ForeignView, Mode } from "./types";
import { useFetch } from "./useFetch";
import { axisUsd, periodLabel, slug, ticks, usd } from "./util";

// Colour follows the region, in the file's fixed order.
const REGION_COLOR: Record<string, string> = {
  europe: "var(--s1)", canada: "var(--s6)", latin_america: "var(--s4)", caribbean: "var(--s5)", asia: "var(--s2)",
  africa: "var(--s3)", oceania: "var(--s7)", organizations: "var(--c-gov_business)", unallocated: "var(--muted)",
};
const SHORT_LIST = 20;

export function ForeignPage({ asset, period }: { asset: string; period?: string }) {
  const { data, error } = useFetch<ForeignView>(`/api/economy/us/foreign/${asset}`);
  if (error) {
    return (
      <main className="page">
        <a href="#/">← Overview</a>
        <p>Could not load foreign holdings: {error}</p>
      </main>
    );
  }
  if (!data) return <main className="page"><p className="muted">Loading…</p></main>;
  return <Foreign view={data} period={period} />;
}

const money = (v: number | null | undefined, signed = false) => (v == null ? "n/a" : usd(v, signed));

/** Sum of a flow over the 12 months ending at i, or null if any month is missing. */
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

function Foreign({ view, period: linked }: { view: ForeignView; period?: string }) {
  const { periods, total, official, regions, countries, quarterly, source, notes } = view;
  const noun = view.id === "treasuries" ? "Treasury securities" : `US ${view.name.toLowerCase()}`;
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

  const [selected, setSelected] = useState(() => [...countries].sort((a, b) => (b.total[last] ?? 0) - (a.total[last] ?? 0))[0].id);
  const [mode, setMode] = useState<Mode>("usd");
  const [all, setAll] = useState(false);

  const ranked = useMemo(
    () => [...countries].sort((a, b) => (b.total[month] ?? -1) - (a.total[month] ?? -1)),
    [countries, month],
  );
  const shown = all ? ranked : ranked.slice(0, SHORT_LIST);
  const country = countries.find((c) => c.id === selected) ?? ranked[0];
  const fill = REGION_COLOR[country.region ?? "organizations"];
  const grand = total.total[month] ?? 0;
  const yearAgo = month >= 12 ? month - 12 : null;
  const stack = regions.map((r) => ({ id: r.region, name: r.name, color: REGION_COLOR[r.region], values: r.total }));
  const z1 = quarterly?.level[month];

  return (
    <main className="page">
      <header className="header">
        <div>
          <a className="back" href="#/">
            ← Overview
          </a>
          <h1>Foreign holders of {noun}</h1>
          <p className="muted">
            The "rest of the world" in the quarterly accounts, split by country each month through {periodLabel(periods[last])}.{" "}
            {quarterly && <a href={`#/us/instrument/${quarterly.instrument_id}`}>All holders of {quarterly.instrument_name.toLowerCase()} →</a>}
          </p>
          <div className="segmented" role="group" aria-label="Kind of security">
            {view.assets.map((a) => (
              <button key={a.id} aria-pressed={a.id === view.id} onClick={() => (window.location.hash = `#/us/foreign/${a.id}`)}>
                {a.name}
              </button>
            ))}
          </div>
        </div>
        <div className="hero">
          <div className="hero-value">{money(total.total[month])}</div>
          <div className="muted">held abroad, {periodLabel(periods[month])}</div>
        </div>
      </header>

      <TimeBar time={time} />

      <section className="card">
        <div className="tiles">
          <div className="tile">
            <div className="muted">Official holders (central banks, governments)</div>
            <div className="tile-value">{money(official.total[month])}</div>
            <div className="muted">{grand ? `${(((official.total[month] ?? 0) / grand) * 100).toFixed(0)}% of foreign holdings` : ""}</div>
          </div>
          <div className="tile">
            <div className="muted">Private holders</div>
            <div className="tile-value">{money(view.private.total[month])}</div>
            <div className="muted">{yearAgo != null ? `${money((view.private.total[month] ?? 0) - (view.private.total[yearAgo] ?? 0), true)} in 12 months` : ""}</div>
          </div>
          {view.has_bills ? (
            <div className="tile">
              <div className="muted">Bills (one year or less)</div>
              <div className="tile-value">{money(total.short_term[month])}</div>
              <div className="muted">bonds and notes {money(total.long_term[month])}</div>
            </div>
          ) : (
            <div className="tile">
              <div className="muted">Valuation change, 12 months</div>
              <div className="tile-value">{money(trailing(total.long_term_valuation, month), true)}</div>
              <div className="muted">price moves, not purchases</div>
            </div>
          )}
          <div className="tile">
            <div className="muted">Net purchases, 12 months</div>
            <div className="tile-value">{money(trailing(total.total_net, month), true)}</div>
            <div className="muted">{trailing(total.total_net, month) == null ? "reported from Feb 2023" : view.has_bills ? "bills and bonds together" : ""}</div>
          </div>
        </div>
        <p className="muted small">{notes.custody}</p>
        {quarterly && z1 != null && (
          <p className="muted small">
            Quarterly accounts, {quarterly.instrument_name.toLowerCase()} held by the rest of the world: {usd(z1)}. {quarterly.note}
          </p>
        )}
      </section>

      <section className="card">
        <div className="card-head">
          <h2>By region over time</h2>
          <div className="controls">
            <ModeToggle mode={mode} onChange={setMode} gdp={false} />
          </div>
        </div>
        <StackedChart series={stack} time={time} mode={mode} selected={country.region} ariaLabel={`Foreign holdings of ${noun} by region, monthly`} events={[]} />
        <div className="legend-row">
          {stack.map((s) => (
            <span key={s.id}>
              <span className="swatch" style={{ background: s.color }} />
              {s.name}
            </span>
          ))}
        </div>
      </section>

      <section className="card">
        <div className="scroll-x">
          <table className="table holders foreign">
            <caption>Holders by country, {periodLabel(periods[month])}. Pick one to see its history.</caption>
            <thead>
              <tr>
                <th>Country</th>
                <th className="num">Holdings</th>
                <th className="num">Share</th>
                {view.has_bills && <th className="num">Of which bills</th>}
                <th className="num">Change, 12 months</th>
                <th className="num">Net purchases, 12 months</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((c, rank) => {
                const on = c.id === country.id;
                const level = c.total[month];
                const before = yearAgo != null ? c.total[yearAgo] : null;
                return (
                  <tr key={c.id} className={on ? "selected" : ""} onClick={() => setSelected(c.id)}>
                    <td>
                      <button className="row-button" aria-pressed={on}>
                        <span className="swatch" style={{ background: REGION_COLOR[c.region ?? "organizations"] }} />
                        {rank + 1}. {c.name}
                      </button>{" "}
                      <a className="row-link" href={`#/country/${slug(c.name)}`} aria-label={`${c.name}: all its links with the US`} onClick={(e) => e.stopPropagation()}>
                        →
                      </a>
                    </td>
                    <td className="num">{money(level)}</td>
                    <td className="num">{level != null && grand ? `${((level / grand) * 100).toFixed(1)}%` : "n/a"}</td>
                    {view.has_bills && <td className="num">{money(c.short_term[month])}</td>}
                    <td className="num">{level != null && before != null ? usd(level - before, true) : "n/a"}</td>
                    <td className="num">{money(trailing(c.total_net, month), true)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <button className="link-button" onClick={() => setAll(!all)}>
          {all ? `Show the top ${SHORT_LIST}` : `Show all ${ranked.length} countries`}
        </button>
      </section>

      <section className="card">
        <div className="card-head">
          <h2>
            <span className="swatch" style={{ background: fill }} />
            {country.name}
          </h2>
          <p className="muted">
            {money(country.total[month])} in {periodLabel(periods[month])} · <a href={`#/country/${slug(country.name)}`}>All its links with the US →</a>
          </p>
        </div>
        <CountryCharts holder={country} fill={fill} time={time} bills={view.has_bills} noun={noun} />
      </section>

      <footer className="footer muted">
        <p>
          Source: <a href={source.url}>{source.name}</a>. Latest month {periodLabel(source.latest)}.
        </p>
        <p>{notes.scope} {notes.valuation}</p>
        {notes.unallocated && <p>{notes.unallocated}</p>}
        <p>{notes.other}</p>
        <p>{notes.history}</p>
        <p>{notes.missing}</p>
      </footer>
    </main>
  );
}

function CountryCharts({ holder, fill, time, bills, noun }: { holder: ForeignHolder; fill: string; time: TimeControls; bills: boolean; noun: string }) {
  const { periods, start, end, period } = time;
  let hi = 0, flowLo = 0, flowHi = 0;
  for (let i = start; i <= end; i++) {
    hi = Math.max(hi, holder.total[i] ?? 0);
    const net = holder.total_net[i];
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
  const hasFlows = holder.total_net.some((v, i) => v != null && i >= start && i <= end);

  return (
    <div className="detail-charts">
      <figure>
        <figcaption>Holdings</figcaption>
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
          events={[]}
          ariaLabel={`${holder.name}: holdings of ${noun} each month`}
          tooltip={(i) => [
            { key: "total", label: "holdings", value: money(holder.total[i]), color: fill },
            ...(bills
              ? [
                  { key: "long", label: "bonds and notes", value: money(holder.long_term[i]) },
                  { key: "short", label: "bills", value: money(holder.short_term[i]) },
                ]
              : []),
          ]}
        >
          {({ x, y }) => {
            const points = [];
            for (let i = start; i <= end; i++) if (holder.total[i] != null) points.push(`${x(i)},${y(holder.total[i]!)}`);
            if (!points.length) return null;
            return (
              <>
                <path d={`M${points.join(" L")}`} fill="none" stroke={fill} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
                {holder.total[period] != null && (
                  <circle cx={x(period)} cy={y(holder.total[period]!)} r={4} fill={fill} stroke="var(--surface)" strokeWidth={2} />
                )}
              </>
            );
          }}
        </Chart>
      </figure>
      <figure>
        <figcaption>Net purchases each month{hasFlows ? "" : " (reported from Feb 2023)"}</figcaption>
        <Chart
          periods={periods}
          start={start}
          end={end}
          domain={flowDomain}
          yTicks={flowTicks}
          formatY={(v) => axisUsd(v, abs(flowDomain))}
          height={200}
          period={period}
          onPeriod={time.choose}
          banded
          events={[]}
          ariaLabel={`${holder.name}: net purchases of ${noun} each month`}
          tooltip={(i) => [
            { key: "net", label: "net purchases", value: money(holder.total_net[i], true), color: fill },
            { key: "valuation", label: bills ? "valuation, bonds and notes" : "valuation", value: money(holder.long_term_valuation[i], true) },
            { key: "other", label: "other change (computed)", value: money(holder.long_term_other[i], true) },
          ]}
        >
          {({ x, y, step }) => {
            const width = Math.max(1, Math.min(16, step - 2));
            const bars = [];
            for (let i = start; i <= end; i++) {
              const v = holder.total_net[i];
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
