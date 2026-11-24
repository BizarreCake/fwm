import { useState } from "react";
import { FlowDiagram } from "./FlowDiagram";
import { MeasureCharts } from "./MeasureCharts";
import { StackedChart } from "./StackedChart";
import { TimeBar, useTimeControls } from "./time";
import type { HoldersView, Mode } from "./types";
import { useFetch } from "./useFetch";
import { color, pct, periodLabel, usd } from "./util";

export function TreasuryPage() {
  const { data, error } = useFetch<HoldersView>("/api/treasury/holders");
  if (error) return <main className="page"><p>Could not load data: {error}</p></main>;
  if (!data) return <main className="page"><p className="muted">Loading…</p></main>;
  return <Treasury view={data} />;
}

function Treasury({ view }: { view: HoldersView }) {
  const { groups, periods, totals, source, notes } = view;
  const time = useTimeControls(periods);
  const [selected, setSelected] = useState("fed");
  const [mode, setMode] = useState<Mode>("usd");

  const period = time.period;
  const group = groups.find((g) => g.id === selected) ?? groups[0];
  const held = totals.holders_market.level[period];
  const face = totals.liability_face.level[period];
  const gap = totals.valuation_gap.level[period];
  const allOther = totals.holders_market.other_change[period];

  return (
    <main className="page">
      <header className="header">
        <div>
          <h1>Who holds US Treasuries</h1>
          <p className="muted">Marketable Treasury securities by holder sector, quarterly.</p>
        </div>
        <div className="hero">
          <div className="hero-value">{usd(face)}</div>
          <div className="muted">
            outstanding at face value, {periodLabel(periods[period])}
            <br />
            {usd(held)} at market value ({usd(-gap, true)} valuation gap)
          </div>
        </div>
      </header>

      <TimeBar time={time} />

      <section className="card split">
        <div>
          <h2>Holders, {periodLabel(periods[period])}</h2>
          <FlowDiagram groups={groups} period={period} selected={selected} onSelect={setSelected} />
        </div>
        <table className="table holders">
          <thead>
            <tr>
              <th>Holder</th>
              <th className="num">Held</th>
              <th className="num">Share</th>
              <th className="num">Net purchases</th>
              <th className="num">Valuation &amp; other</th>
            </tr>
          </thead>
          <tbody>
            {groups.map((g) => {
              const other = g.other_change[period];
              return (
                <tr key={g.id} className={g.id === selected ? "selected" : ""} onClick={() => setSelected(g.id)}>
                  <td>
                    <button className="row-button" aria-pressed={g.id === selected}>
                      <span className="swatch" style={{ background: color(g.id) }} />
                      {g.name}
                    </button>
                  </td>
                  <td className="num">{usd(g.level[period])}</td>
                  <td className="num">{pct(g.level[period] / (held || 1))}</td>
                  <td className="num">{usd(g.transactions[period], true)}</td>
                  <td className="num">{other === null ? "–" : usd(other, true)}</td>
                </tr>
              );
            })}
          </tbody>
          <tfoot>
            <tr>
              <td>All holders</td>
              <td className="num">{usd(held)}</td>
              <td className="num">100%</td>
              <td className="num">{usd(totals.holders_market.transactions[period], true)}</td>
              <td className="num">{allOther === null ? "–" : usd(allOther, true)}</td>
            </tr>
          </tfoot>
        </table>
      </section>

      <section className="card">
        <div className="card-head">
          <h2>Holdings over time</h2>
          <ModeToggle mode={mode} onChange={setMode} />
        </div>
        <StackedChart
          series={groups.map((g) => ({ id: g.id, name: g.name, color: color(g.id), values: g.level }))}
          time={time}
          mode={mode}
          selected={selected}
          ariaLabel="Treasury holdings by holder group over time"
        />
        <div className="legend-row">
          {groups.map((g) => (
            <button key={g.id} className="row-button" aria-pressed={g.id === selected} onClick={() => setSelected(g.id)}>
              <span className="swatch" style={{ background: color(g.id) }} />
              {g.name}
            </button>
          ))}
        </div>
      </section>

      <section className="card">
        <div className="card-head">
          <h2>
            <span className="swatch" style={{ background: color(group.id) }} />
            {group.name}
          </h2>
          <p className="muted">{group.note}</p>
        </div>
        <MeasureCharts name={group.name} measures={group} fill={color(group.id)} time={time} />
        <div className="scroll-x">
          <table className="table">
            <caption>
              {group.sectors.length > 1 ? "Sectors in this group" : "Sector"}, {periodLabel(periods[period])}. Open a sector to see its
              whole balance sheet.
            </caption>
            <thead>
              <tr>
                <th>Sector</th>
                <th className="num">Held</th>
                <th className="num">Net purchases</th>
                <th className="num">Valuation &amp; other</th>
                <th>Z.1 series</th>
              </tr>
            </thead>
            <tbody>
              {[...group.sectors]
                .sort((a, b) => b.level[period] - a.level[period])
                .map((sector) => {
                  const other = sector.other_change[period];
                  return (
                    <tr key={sector.code}>
                      <td>{sector.sector_id ? <a href={`#/sector/${sector.sector_id}`}>{sector.name} →</a> : sector.name}</td>
                      <td className="num">{usd(sector.level[period])}</td>
                      <td className="num">{usd(sector.transactions[period], true)}</td>
                      <td className="num">{other === null ? "–" : usd(other, true)}</td>
                      <td className="series">
                        {sector.level_series} <span className="basis">{sector.basis === "market" ? "market value" : "book value"}</span>
                      </td>
                    </tr>
                  );
                })}
            </tbody>
          </table>
        </div>
      </section>

      <footer className="footer muted">
        <p>
          Source: <a href={source.url}>{source.name}</a>, table {source.table}. Latest quarter {periodLabel(source.latest_period)}
          {source.published_at && <>; release published {source.published_at.slice(0, 10)}</>}. Figures are observed sector aggregates as
          published.
        </p>
        <p>{notes.valuation}</p>
        <p>Valuation &amp; other: {notes.other_change}</p>
        <p>{notes.coverage}</p>
      </footer>
    </main>
  );
}

export function ModeToggle({ mode, onChange }: { mode: Mode; onChange: (mode: Mode) => void }) {
  return (
    <div className="segmented" role="group" aria-label="Scale">
      <button aria-pressed={mode === "usd"} onClick={() => onChange("usd")}>
        Dollars
      </button>
      <button aria-pressed={mode === "share"} onClick={() => onChange("share")}>
        Share
      </button>
    </div>
  );
}
