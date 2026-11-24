import { useState } from "react";
import { MeasureCharts } from "./MeasureCharts";
import type { TimeControls } from "./time";
import type { WhoToWhomView } from "./types";
import { useFetch } from "./useFetch";
import { api, base, color, pct, periodLabel, usd } from "./util";

/** What each sector holds of each sector's paper in the selected quarter, with one pair's history beneath. */
export function WhoToWhomCard({ instrumentId, time }: { instrumentId: string; time: TimeControls }) {
  const { data, error } = useFetch<WhoToWhomView>(api(`who-to-whom/${instrumentId}`));
  const [picked, setPicked] = useState<{ holder: string; issuer: string } | null>(null);
  if (error) return <section className="card"><p className="muted">Could not load holdings by counterpart: {error}</p></section>;
  if (!data) return <section className="card"><p className="muted">Loading holdings by counterpart…</p></section>;

  const i = time.period;
  const quarter = periodLabel(data.periods[i]);
  const at = (holder: string, issuer: string) => data.matrix[holder]?.[issuer]?.level[i] ?? null;
  const available = data.periods[i] >= data.first_period;
  // The pair's charts start where the matrix does, so quarters without data are not drawn as zero.
  const pairTime = { ...time, start: Math.max(time.start, data.periods.indexOf(data.first_period)) };

  const rowTotal = (holder: string) => data.issuers.reduce((sum, issuer) => sum + (at(holder, issuer) ?? 0), 0);
  const columnTotal = (issuer: string) => data.holders.reduce((sum, holder) => sum + (at(holder, issuer) ?? 0), 0);
  const total = data.holders.reduce((sum, holder) => sum + rowTotal(holder), 0);
  let largest = 0;
  let top: { holder: string; issuer: string } | null = null;
  for (const holder of data.holders) {
    for (const issuer of data.issuers) {
      const value = at(holder, issuer) ?? 0;
      if (value > largest) {
        largest = value;
        top = { holder, issuer };
      }
    }
  }
  const pair = picked && data.matrix[picked.holder]?.[picked.issuer] ? picked : top;
  const cell = pair ? data.matrix[pair.holder][pair.issuer] : null;
  const name = (id: string) => data.sectors[id].name;
  const short = (id: string) => SHORT[id] ?? name(id);

  return (
    <section className="card">
      <div className="card-head">
        <h2>Who holds whose, {quarter}</h2>
        <p className="muted">Rows hold; columns owe. Darker cells are larger. Select a cell for its history.</p>
      </div>
      {!available ? (
        <p className="muted">
          Holdings by counterpart for this instrument start in {periodLabel(data.first_period)}. Move the quarter forward to see them.
        </p>
      ) : (
        <div className="scroll-x">
          <table className="table matrix">
            <thead>
              <tr>
                <th>Holder ↓ &nbsp; Issuer →</th>
                {data.issuers.map((issuer) => (
                  <th key={issuer} className="num" title={name(issuer)}>
                    <span className="swatch" style={{ background: color(data.sectors[issuer].group) }} /> {short(issuer)}
                  </th>
                ))}
                <th className="num">All issuers</th>
              </tr>
            </thead>
            <tbody>
              {data.holders.map((holder) => (
                <tr key={holder}>
                  <th scope="row">
                    <span className="swatch" style={{ background: color(data.sectors[holder].group) }} />{" "}
                    <a href={`${base()}/sector/${holder}`} title={name(holder)}>{short(holder)}</a>
                  </th>
                  {data.issuers.map((issuer) => {
                    const value = at(holder, issuer);
                    if (value === null) {
                      return (
                        <td key={issuer} className="num muted">
                          –
                        </td>
                      );
                    }
                    const on = pair?.holder === holder && pair.issuer === issuer;
                    // One hue, light to dark, by size relative to the largest cell. The number stays in text ink.
                    const strength = largest > 0 ? Math.sqrt(Math.max(0, value) / largest) : 0;
                    return (
                      <td key={issuer} className="num cell" style={{ background: `color-mix(in srgb, var(--s1) ${Math.round(strength * 38)}%, transparent)` }}>
                        <button
                          className={on ? "cell-button on" : "cell-button"}
                          aria-pressed={on}
                          title={`${name(holder)} holds ${usd(value)} owed by ${name(issuer)} (${pct(total ? value / total : 0)} of the total)`}
                          onClick={() => setPicked({ holder, issuer })}
                        >
                          {usd(value)}
                        </button>
                      </td>
                    );
                  })}
                  <td className="num strong">{usd(rowTotal(holder))}</td>
                </tr>
              ))}
              <tr>
                <th scope="row">All holders</th>
                {data.issuers.map((issuer) => (
                  <td key={issuer} className="num strong">
                    {usd(columnTotal(issuer))}
                  </td>
                ))}
                <td className="num strong">{usd(total)}</td>
              </tr>
            </tbody>
          </table>
        </div>
      )}
      {available && pair && cell && (
        <>
          <h3 className="pair-title">
            {name(pair.holder)} <span className="muted">holding paper of</span> {name(pair.issuer)}
            {cell.computed && <span className="basis"> computed as the remainder</span>}
          </h3>
          <MeasureCharts name={`${name(pair.holder)} → ${name(pair.issuer)}`} measures={cell} fill={color(data.sectors[pair.holder].group)} time={pairTime} />
        </>
      )}
      <p className="muted small">
        {data.notes.reading} {data.notes.rest_of_world} {data.notes.coverage}
      </p>
    </section>
  );
}

const SHORT: Record<string, string> = {
  S11: "Non-fin. corporations",
  S12K: "Banks & central banks",
  S124: "Investment funds",
  S12O: "Other financial",
  S128: "Insurers",
  S129: "Pension funds",
  S13: "Government",
  S1M: "Households",
  ROW: "Rest of world",
};
