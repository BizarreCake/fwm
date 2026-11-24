import { useState } from "react";
import { Chart } from "./Chart";
import type { CountryLinks as Links, CountryLinksSide } from "./types";
import { useFetch } from "./useFetch";
import { axisUsd, periodLabel, ticks, usd } from "./util";

// Colour follows who reports the figure: the country itself, or the other countries.
const SIDE_COLOR = { own: "var(--s1)", mirror: "var(--s2)" } as const;

const lastIndex = (values: (number | null)[]): number => {
  for (let i = values.length - 1; i >= 0; i--) if (values[i] !== null) return i;
  return -1;
};

/** A country's positions with every other country: what it reports, and what the others report about it. */
export function CountryLinksCard({ countryId, name }: { countryId: string; name: string }) {
  const { data } = useFetch<Links>(`/api/countries/${countryId}/links`);
  const [kindId, setKindId] = useState("debt");
  if (!data) return null;
  const kind = data.kinds.find((k) => k.id === kindId) ?? data.kinds[0];
  const sides = (["own", "mirror"] as const).map((id) => ({ id, side: kind[id] }));
  const series = sides.flatMap(({ id, side }) => (side && lastIndex(side.series) >= 0 ? [{ id, side }] : []));
  const max = Math.max(1, ...series.flatMap((s) => s.side.series.map((v) => v ?? 0)));
  const yTicks = ticks(0, max, 3);
  const domain: [number, number] = [0, Math.max(max, yTicks[yTicks.length - 1])];
  const upTo = (values: (number | null)[], i: number) => {
    for (let k = i; k >= Math.max(0, i - 3); k--) if (values[k] !== null) return values[k];
    return null;
  };
  const legend = { own: `Reported by ${name}`, mirror: `Reported by other countries about ${name}` };

  return (
    <section className="card" id="links">
      <div className="card-head">
        <h2>{name} and the rest of the world</h2>
        <div className="segmented" role="group" aria-label="Kind of position">
          {data.kinds.map((k) => (
            <button key={k.id} aria-pressed={k.id === kind.id} onClick={() => setKindId(k.id)}>
              {k.name}
            </button>
          ))}
        </div>
      </div>
      <p className="muted">
        {kind.source === "IMF" ? "IMF portfolio investment survey" : "BIS locational banking statistics"}, {kind.frequency}, US dollars. {data.notes.reading}
      </p>
      <div className="detail-charts">
        {sides.map(({ id, side }) => (
          <SideTable key={id} side={side} color={SIDE_COLOR[id]} name={name} own={id === "own"} />
        ))}
      </div>
      {series.length > 0 && (
        <figure>
          <figcaption>Totals over time</figcaption>
          <div className="legend-row">
            {series.map((s) => (
              <span key={s.id}>
                <span className="swatch" style={{ background: SIDE_COLOR[s.id] }} />
                {legend[s.id]}
              </span>
            ))}
          </div>
          <Chart
            periods={kind.periods}
            start={0}
            end={kind.periods.length - 1}
            domain={domain}
            yTicks={yTicks}
            formatY={(v) => axisUsd(v, domain[1])}
            height={200}
            period={-1}
            onPeriod={() => {}}
            events={[]}
            ariaLabel={`${kind.name}: ${name}'s total abroad and other countries' total with ${name}, over time`}
            tooltip={(i) =>
              series.flatMap((s) => {
                const value = upTo(s.side.series, i);
                return value === null ? [] : [{ key: s.id, label: legend[s.id], value: usd(value), color: SIDE_COLOR[s.id] }];
              })
            }
          >
            {({ x, y }) => (
              <>
                {series.map((s) => {
                  const points = s.side.series.flatMap((v, i) => (v === null ? [] : [`${x(i)},${y(v)}`]));
                  const at = lastIndex(s.side.series);
                  return (
                    <g key={s.id}>
                      <path d={`M${points.join(" L")}`} fill="none" stroke={SIDE_COLOR[s.id]} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
                      <circle cx={x(at)} cy={y(s.side.series[at]!)} r={4} fill={SIDE_COLOR[s.id]} stroke="var(--surface)" strokeWidth={2} />
                    </g>
                  );
                })}
              </>
            )}
          </Chart>
        </figure>
      )}
      <p className="muted small">
        {data.notes.mirror} {data.notes.custody} Sources: <a href={data.source.imf}>IMF</a>, <a href={data.source.bis}>BIS</a>.{" "}
        <a href="#/links">Links between the large economies →</a>
      </p>
    </section>
  );
}

function SideTable({ side, color, name, own }: { side: CountryLinksSide | null; color: string; name: string; own: boolean }) {
  if (!side) {
    return <p className="muted">{own ? `${name} does not report this.` : `No other country reports this about ${name}.`}</p>;
  }
  const largest = Math.max(1, ...side.top.map((row) => row.value), side.everywhere_else ?? 0);
  const share = (value: number) => (side.total ? `${((value / side.total) * 100).toFixed(1)}%` : "");
  return (
    <div className="scroll-x">
      <h3 className="pair-title">
        <span className="swatch" style={{ background: color, marginRight: 6 }} />
        {side.label}, {periodLabel(side.period)}
      </h3>
      <table className="table compare">
        <thead>
          <tr>
            <th>Country</th>
            <th className="num">Amount</th>
            <th className="num">Share</th>
            <th aria-hidden="true" />
          </tr>
        </thead>
        <tbody>
          {side.top.length === 0 && (
            <tr>
              <td colSpan={4} className="muted">
                Published only in total, not by country.
              </td>
            </tr>
          )}
          {side.top.map((row) => (
            <tr key={row.iso2}>
              <td>{row.page ? <a href={`#/country/${row.page}`}>{row.name}</a> : row.name}</td>
              <td className="num">{usd(row.value)}</td>
              <td className="num">{share(row.value)}</td>
              <td className="compare-bars" aria-hidden="true">
                <div className="compare-bar" style={{ width: `${(row.value / largest) * 100}%`, background: color }} />
              </td>
            </tr>
          ))}
          {side.top.length > 0 && side.everywhere_else !== null && (
            <tr>
              <td className="muted">Everywhere else</td>
              <td className="num">{usd(side.everywhere_else)}</td>
              <td className="num">{share(side.everywhere_else)}</td>
              <td className="compare-bars" aria-hidden="true">
                <div className="compare-bar" style={{ width: `${Math.max(0, (side.everywhere_else / largest) * 100)}%`, background: "var(--muted)" }} />
              </td>
            </tr>
          )}
        </tbody>
        <tfoot>
          <tr>
            <td>
              Total
              {side.reporters != null && !own && side.in_us_dollars === undefined ? `, ${side.reporters} countries reporting` : ""}
              {side.in_us_dollars != null && side.total ? `, ${((side.in_us_dollars / side.total) * 100).toFixed(0)}% in US dollars` : ""}
            </td>
            <td className="num">{side.total === null ? "n/a" : usd(side.total)}</td>
            <td />
            <td />
          </tr>
        </tfoot>
      </table>
    </div>
  );
}
