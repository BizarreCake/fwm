import { useState } from "react";
import { FlowDiagram } from "./FlowDiagram";
import { MeasureCharts } from "./MeasureCharts";
import { ModeToggle } from "./ModeToggle";
import { StackedChart } from "./StackedChart";
import { TimeBar, useTimeControls } from "./time";
import type { Group, InstrumentSummary, InstrumentView, Mode, SideName, SideView } from "./types";
import { useFetch } from "./useFetch";
import { color, pct, periodLabel, usd } from "./util";

const SIDE_TITLE: Record<SideName, string> = { holders: "Holders", issuers: "Issuers" };

export function InstrumentPage({ instrumentId }: { instrumentId: string }) {
  const { data, error } = useFetch<InstrumentView>(`/api/instruments/${instrumentId}`);
  if (error) {
    return (
      <main className="page">
        <a href="#/">← Overview</a>
        <p>Could not load this instrument: {error}</p>
      </main>
    );
  }
  if (!data) return <main className="page"><p className="muted">Loading…</p></main>;
  return <Instrument view={data} />;
}

function largest(side: SideView): string {
  const last = side.level.length - 1;
  return [...side.groups].sort((a, b) => (b.level[last] ?? 0) - (a.level[last] ?? 0))[0].id;
}

function Instrument({ view }: { view: InstrumentView }) {
  const { periods, holders, issuers, discrepancy, source, notes } = view;
  const time = useTimeControls(periods);
  const period = time.period;
  const instruments = useFetch<InstrumentSummary[]>("/api/instruments").data;
  const [selected, setSelected] = useState<{ side: SideName; id: string }>({ side: "holders", id: largest(holders) });
  const [mode, setMode] = useState<Mode>("usd");

  const side = selected.side === "issuers" && issuers ? issuers : holders;
  const sideName: SideName = side === issuers ? "issuers" : "holders";
  const group = side.groups.find((g) => g.id === selected.id) ?? side.groups[0];
  const select = (name: SideName, id: string) => setSelected({ side: name, id });
  const held = holders.level[period] ?? 0;
  const owed = issuers?.level[period] ?? null;
  const gap = discrepancy?.level[period] ?? null;

  const table = (name: SideName, data: SideView) => {
    const total = data.level[period] ?? 0;
    return (
      <div className="scroll-x">
        <table className="table holders">
          <thead>
            <tr>
              <th>{SIDE_TITLE[name]}</th>
              <th className="num">Amount</th>
              <th className="num">Share</th>
              <th className="num">Net transactions</th>
            </tr>
          </thead>
          <tbody>
            {data.groups.map((g) => {
              const on = sideName === name && g.id === group.id;
              return (
                <tr key={g.id} className={on ? "selected" : ""} onClick={() => select(name, g.id)}>
                  <td>
                    <button className="row-button" aria-pressed={on}>
                      <span className="swatch" style={{ background: color(g.id) }} />
                      {g.name}
                    </button>
                  </td>
                  <td className="num">{usd(g.level[period] ?? 0)}</td>
                  <td className="num">{total ? pct((g.level[period] ?? 0) / total) : "–"}</td>
                  <td className="num">{g.transactions[period] === null ? "–" : usd(g.transactions[period]!, true)}</td>
                </tr>
              );
            })}
          </tbody>
          <tfoot>
            <tr>
              <td>All {SIDE_TITLE[name].toLowerCase()}</td>
              <td className="num">{usd(total)}</td>
              <td className="num">100%</td>
              <td className="num">{data.transactions[period] === null ? "–" : usd(data.transactions[period]!, true)}</td>
            </tr>
          </tfoot>
        </table>
      </div>
    );
  };

  return (
    <main className="page">
      <header className="header">
        <div>
          <a className="back" href="#/">
            ← Overview
          </a>
          <h1>{view.name}</h1>
          <p className="muted">
            Who holds it and who owes it, by sector, quarterly.{" "}
            {instruments && (
              <select
                className="picker"
                aria-label="Instrument"
                value={view.id}
                onChange={(e) => (window.location.hash = `#/instrument/${e.target.value}`)}
              >
                {instruments.map((i) => (
                  <option key={i.id} value={i.id}>
                    {i.name}
                  </option>
                ))}
              </select>
            )}
          </p>
        </div>
        <div className="hero">
          <div className="hero-value">{usd(held)}</div>
          <div className="muted">
            held, {periodLabel(periods[period])}
            {owed !== null && (
              <>
                <br />
                {usd(owed)} owed by issuers
                {gap !== null && Math.abs(gap) >= 0.5 && <> ({usd(gap, true)} discrepancy)</>}
              </>
            )}
          </div>
        </div>
      </header>

      <TimeBar time={time} />

      <section className="card">
        <h2>Issuers and holders, {periodLabel(periods[period])}</h2>
        <FlowDiagram
          name={view.name}
          issuers={issuers?.groups ?? null}
          holders={holders.groups}
          period={period}
          selected={{ side: sideName, id: group.id }}
          onSelect={select}
        />
        <div className={issuers ? "tables" : "tables single"}>
          {issuers && table("issuers", issuers)}
          {table("holders", holders)}
        </div>
        {!issuers && notes.issuers && <p className="muted">{notes.issuers}</p>}
      </section>

      <section className="card">
        <div className="card-head">
          <h2>{SIDE_TITLE[sideName]} over time</h2>
          <div className="controls">
            {issuers && (
              <div className="segmented" role="group" aria-label="Side">
                <button aria-pressed={sideName === "holders"} onClick={() => select("holders", largest(holders))}>
                  Holders
                </button>
                <button aria-pressed={sideName === "issuers"} onClick={() => select("issuers", largest(issuers))}>
                  Issuers
                </button>
              </div>
            )}
            <ModeToggle mode={mode} onChange={setMode} />
          </div>
        </div>
        <StackedChart
          series={side.groups.map((g) => ({ id: g.id, name: g.name, color: color(g.id), values: g.level }))}
          time={time}
          mode={mode}
          selected={group.id}
          ariaLabel={`${view.name}: ${sideName} by sector group over time`}
        />
        <div className="legend-row">
          {side.groups.map((g) => (
            <button key={g.id} className="row-button" aria-pressed={g.id === group.id} onClick={() => select(sideName, g.id)}>
              <span className="swatch" style={{ background: color(g.id) }} />
              {g.name}
            </button>
          ))}
        </div>
      </section>

      <GroupDetail group={group} sideName={sideName} time={time} />

      <footer className="footer muted">
        <p>
          Source: <a href={source.url}>{source.name}</a>, table {source.table}. Latest quarter {periodLabel(source.latest_period)}
          {source.published_at && <>; release published {source.published_at.slice(0, 10)}</>}. Figures are observed sector aggregates as
          published.
        </p>
        <p>{notes.sides}</p>
        <p>{notes.other_change}</p>
        <p>{notes.coverage}</p>
      </footer>
    </main>
  );
}

function GroupDetail({ group, sideName, time }: { group: Group; sideName: SideName; time: ReturnType<typeof useTimeControls> }) {
  const period = time.period;
  return (
    <section className="card">
      <div className="card-head">
        <h2>
          <span className="swatch" style={{ background: color(group.id) }} />
          {group.name}
        </h2>
        <p className="muted">as {sideName === "holders" ? "holders" : "issuers"}</p>
      </div>
      <MeasureCharts name={group.name} measures={group} fill={color(group.id)} time={time} />
      <div className="scroll-x">
        <table className="table">
          <caption>
            {group.sectors.length > 1 ? "Sectors in this group" : "Sector"}, {periodLabel(time.periods[period])}. Open a sector to see its
            whole balance sheet.
          </caption>
          <thead>
            <tr>
              <th>Sector</th>
              <th className="num">Amount</th>
              <th className="num">Net transactions</th>
              <th className="num">Valuation &amp; other</th>
              <th>Z.1 series</th>
            </tr>
          </thead>
          <tbody>
            {[...group.sectors]
              .sort((a, b) => (b.level[period] ?? 0) - (a.level[period] ?? 0))
              .map((sector) => (
                <tr key={sector.series}>
                  <td title={sector.detail}>
                    {sector.sector_id ? <a href={`#/sector/${sector.sector_id}`}>{sector.name} →</a> : sector.name}
                  </td>
                  <td className="num">{sector.level[period] === null ? "–" : usd(sector.level[period]!)}</td>
                  <td className="num">{sector.transactions[period] === null ? "–" : usd(sector.transactions[period]!, true)}</td>
                  <td className="num">{sector.other_change[period] === null ? "–" : usd(sector.other_change[period]!, true)}</td>
                  <td className="series">
                    {sector.series} <span className="basis">{sector.basis === "market" ? "market value" : "book value"}</span>
                  </td>
                </tr>
              ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
