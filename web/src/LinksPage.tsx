import { useState } from "react";
import { Chart } from "./Chart";
import type { LinkKind, LinksView } from "./types";
import { useFetch } from "./useFetch";
import { axisUsd, periodLabel, ticks, usd } from "./util";

// Colour follows the economy wherever economies share a chart.
const AREA_COLOR: Record<string, string> = {
  us: "var(--s1)",
  ea: "var(--s2)",
  jp: "var(--s3)",
  uk: "var(--s4)",
  cn: "var(--s5)",
  ky: "var(--s6)",
};

const last = (values: (number | null)[]): number => {
  for (let i = values.length - 1; i >= 0; i--) if (values[i] !== null) return i;
  return -1;
};

/** How economies are tied to each other: securities held across borders, and banks' positions with other economies. */
export function LinksPage({ pair }: { pair?: string }) {
  const { data, error } = useFetch<LinksView>("/api/links");
  const [kindId, setKindId] = useState("equity");
  if (error) return <main className="page"><p>Could not load links between economies: {error}</p></main>;
  if (!data) return <main className="page"><p className="muted">Loading…</p></main>;

  const ids = data.areas.map((area) => area.id);
  const [givenA, givenB] = (pair ?? "").split("-");
  const a = ids.includes(givenA) ? givenA : "us";
  const b = ids.includes(givenB) && givenB !== a ? givenB : a === "ea" ? "us" : "ea";
  const name = (id: string) => data.column_names[id];
  const choose = (first: string, second: string) => {
    window.location.hash = `#/links?pair=${first}-${second}`;
  };

  return (
    <main className="page">
      <header className="header">
        <div>
          <h1>Links between economies</h1>
          <p className="muted">
            Who holds whose securities, and what banks in one economy owe and are owed by another. In US dollars.{" "}
            <a href="#/">US overview</a> · <a href="#/ea">Euro area overview</a> · <a href="#/jp">Japan overview</a>
          </p>
        </div>
      </header>

      <section className="card">
        <div className="card-head">
          <h2>
            {name(a)} and {name(b)}
          </h2>
          <div className="pair-pick">
            <label>
              <span className="muted">Between</span>{" "}
              <select value={a} onChange={(e) => choose(e.target.value, e.target.value === b ? a : b)} aria-label="First economy">
                {data.areas.map((area) => (
                  <option key={area.id} value={area.id}>
                    {area.name}
                  </option>
                ))}
              </select>
            </label>{" "}
            <label>
              <span className="muted">and</span>{" "}
              <select value={b} onChange={(e) => choose(e.target.value === a ? b : a, e.target.value)} aria-label="Second economy">
                {data.areas.map((area) => (
                  <option key={area.id} value={area.id}>
                    {area.name}
                  </option>
                ))}
              </select>
            </label>
          </div>
        </div>
        <PairTable data={data} a={a} b={b} />
        <p className="legend-row">
          <span className="legend">
            <span className="swatch" style={{ background: AREA_COLOR[a] }} /> {name(a)} → {name(b)}
            <span className="swatch" style={{ background: AREA_COLOR[b] }} /> {name(b)} → {name(a)}
          </span>
        </p>
        <div className="detail-charts">
          {data.kinds.map((kind) => (
            <PairChart key={kind.id} kind={kind} a={a} b={b} name={name} />
          ))}
        </div>
        <p className="muted small">
          {data.notes.reading} {data.notes.custody} {data.notes.not_included}
        </p>
      </section>

      <MatrixCard data={data} kindId={kindId} setKindId={setKindId} a={a} b={b} choose={choose} />

      <CurrencyCard data={data} />

      <p className="muted small">
        Sources: <a href={data.source.imf}>IMF, Portfolio Investment Positions by Counterpart Economy</a> (end of June and December) and{" "}
        <a href={data.source.bis}>BIS locational banking statistics</a> (quarterly). {data.notes.euro_area} {data.notes.dollars} {data.notes.against_us_data}
      </p>
    </main>
  );
}

function cellOf(kind: LinkKind, holder: string, issuer: string) {
  return kind.matrix[holder]?.[issuer] ?? null;
}

function PairTable({ data, a, b }: { data: LinksView; a: string; b: string }) {
  const name = (id: string) => data.column_names[id];
  const amount = (kind: LinkKind, holder: string, issuer: string) => {
    const cell = cellOf(kind, holder, issuer);
    const i = cell ? last(cell.level) : -1;
    if (!cell || i < 0) return <span className="muted" title={`${name(holder)} does not publish this by country`}>not published</span>;
    return (
      <>
        {usd(cell.level[i]!)}
        {cell.missing.length > 0 && <span title={`Leaves out ${cell.missing.join(", ")}`}> †</span>}
      </>
    );
  };
  return (
    <div className="scroll-x">
      <table className="table">
        <thead>
          <tr>
            <th />
            <th className="num">
              <span className="swatch" style={{ background: AREA_COLOR[a] }} /> {name(a)} → {name(b)}
            </th>
            <th className="num">
              <span className="swatch" style={{ background: AREA_COLOR[b] }} /> {name(b)} → {name(a)}
            </th>
            <th>As of</th>
          </tr>
        </thead>
        <tbody>
          {data.kinds.map((kind) => (
            <tr key={kind.id}>
              <td>
                {kind.name}
                <div className="muted small">
                  {kind.row_label.toLowerCase()} the first, {kind.column_label.toLowerCase()} the second
                </div>
              </td>
              <td className="num">{amount(kind, a, b)}</td>
              <td className="num">{amount(kind, b, a)}</td>
              <td className="muted">{periodLabel(kind.periods[kind.periods.length - 1])}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Both directions of one kind of position over time. Half-yearly sources leave quarters empty; the line joins what is there. */
function PairChart({ kind, a, b, name }: { kind: LinkKind; a: string; b: string; name: (id: string) => string }) {
  const series = [
    { holder: a, issuer: b },
    { holder: b, issuer: a },
  ]
    .map((s) => ({ ...s, level: cellOf(kind, s.holder, s.issuer)?.level ?? [] }))
    .filter((s) => last(s.level) >= 0);
  const end = kind.periods.length - 1;
  if (series.length === 0) {
    return (
      <figure>
        <figcaption>{kind.name}</figcaption>
        <p className="muted">Neither economy publishes this by country.</p>
      </figure>
    );
  }
  const max = Math.max(1, ...series.flatMap((s) => s.level.map((v) => v ?? 0)));
  const yTicks = ticks(0, max, 3);
  const domain: [number, number] = [0, Math.max(max, yTicks[yTicks.length - 1])];
  // The value shown for a quarter is the latest one published up to then.
  const upTo = (level: (number | null)[], i: number) => {
    for (let k = i; k >= Math.max(0, i - 3); k--) if (level[k] !== null) return level[k];
    return null;
  };
  return (
    <figure>
      <figcaption>
        {kind.name} <span className="basis">{kind.source}, {kind.frequency}</span>
      </figcaption>
      <Chart
        periods={kind.periods}
        start={0}
        end={end}
        domain={domain}
        yTicks={yTicks}
        formatY={(v) => axisUsd(v, domain[1])}
        height={190}
        period={-1}
        onPeriod={() => {}}
        events={[]}
        ariaLabel={`${kind.name} between ${name(a)} and ${name(b)} over time, both directions`}
        tooltip={(i) =>
          series.flatMap((s) => {
            const value = upTo(s.level, i);
            return value === null ? [] : [{ key: s.holder, label: `${name(s.holder)} → ${name(s.issuer)}`, value: usd(value), color: AREA_COLOR[s.holder] }];
          })
        }
      >
        {({ x, y }) => (
          <>
            {series.map((s) => {
              const points = s.level.flatMap((v, i) => (v === null ? [] : [`${x(i)},${y(v)}`]));
              const at = last(s.level);
              return (
                <g key={s.holder}>
                  <path d={`M${points.join(" L")}`} fill="none" stroke={AREA_COLOR[s.holder]} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
                  <circle cx={x(at)} cy={y(s.level[at]!)} r={4} fill={AREA_COLOR[s.holder]} stroke="var(--surface)" strokeWidth={2} />
                </g>
              );
            })}
          </>
        )}
      </Chart>
    </figure>
  );
}

function MatrixCard(props: { data: LinksView; kindId: string; setKindId: (id: string) => void; a: string; b: string; choose: (a: string, b: string) => void }) {
  const { data, kindId, setKindId, a, b, choose } = props;
  const kind = data.kinds.find((k) => k.id === kindId) ?? data.kinds[0];
  const name = (id: string) => data.column_names[id];
  const at = kind.periods.length - 1;
  const value = (holder: string, column: string) => {
    const cell = cellOf(kind, holder, column);
    if (!cell) return null;
    const i = last(cell.level);
    // Only the latest period counts: a pair last published years ago is not shown as current.
    return i >= at - 3 ? cell.level[i] : null;
  };
  const areaIds = data.areas.map((area) => area.id);
  const largest = Math.max(1, ...kind.holders.flatMap((holder) => areaIds.map((issuer) => value(holder, issuer) ?? 0)));
  const reporting = Object.entries(kind.reporting);
  return (
    <section className="card">
      <div className="card-head">
        <h2>
          Every pair, {periodLabel(kind.periods[at])}
        </h2>
        <div className="segmented" role="group" aria-label="Kind of position">
          {data.kinds.map((k) => (
            <button key={k.id} aria-pressed={k.id === kind.id} onClick={() => setKindId(k.id)}>
              {k.name}
            </button>
          ))}
        </div>
      </div>
      <p className="muted">
        {kind.sentence.replace("{holder}", "the row's economy").replace("{issuer}", "the column's economy").replace("{amount}", "the amount shown")}
        . Darker cells are larger. Select a cell to see that pair above.
      </p>
      <div className="scroll-x">
        <table className="table matrix">
          <thead>
            <tr>
              <th>
                {kind.row_label} ↓ &nbsp; {kind.column_label} →
              </th>
              {data.columns.map((column) => (
                <th key={column} className="num">
                  {AREA_COLOR[column] && <span className="swatch" style={{ background: AREA_COLOR[column] }} />} {name(column)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {kind.holders.map((holder) => (
              <tr key={holder}>
                <th scope="row">
                  <span className="swatch" style={{ background: AREA_COLOR[holder] }} /> {name(holder)}
                </th>
                {data.columns.map((column) => {
                  if (column === holder) return <td key={column} className="num muted" />;
                  const v = value(holder, column);
                  if (v === null) {
                    return (
                      <td key={column} className="num muted" title="Not published by country">
                        –
                      </td>
                    );
                  }
                  const cell = cellOf(kind, holder, column)!;
                  const dagger = cell.missing.length > 0 ? " †" : "";
                  if (!areaIds.includes(column)) {
                    return (
                      <td key={column} className={column === "world" ? "num strong" : "num"}>
                        {usd(v)}
                      </td>
                    );
                  }
                  const on = (holder === a && column === b) || (holder === b && column === a);
                  const strength = Math.sqrt(Math.max(0, v) / largest);
                  return (
                    <td key={column} className="num cell" style={{ background: `color-mix(in srgb, var(--s1) ${Math.round(strength * 38)}%, transparent)` }}>
                      <button
                        className={on ? "cell-button on" : "cell-button"}
                        aria-pressed={on}
                        title={
                          kind.sentence.replace("{holder}", name(holder)).replace("{issuer}", name(column)).replace("{amount}", usd(v)) +
                          (dagger ? `. Leaves out ${cell.missing.join(", ")}` : "")
                        }
                        onClick={() => choose(holder, column)}
                      >
                        {usd(v)}
                        {dagger}
                      </button>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="muted small">
        {data.notes.gaps}
        {reporting.map(([holder, names]) => ` ${name(holder)} here is ${names.length} reporting countries: ${names.join(", ")}.`)}
      </p>
    </section>
  );
}

/** All reporting banks worldwide against each economy, by currency: the only place the currency is published. */
function CurrencyCard({ data }: { data: LinksView }) {
  const banks = data.all_banks;
  const end = banks.periods.length - 1;
  if (end < 0) return null;
  const name = (id: string) => (id === "world" ? "All economies" : data.column_names[id]);
  const world = banks.areas.world.claims.usd;
  const us = banks.areas.us.claims.usd;
  const offshore = world.map((v, i) => (v === null || us[i] === null ? null : v - us[i]!));
  const start = offshore.findIndex((v) => v !== null);
  const max = Math.max(1, ...offshore.map((v) => v ?? 0));
  const yTicks = ticks(0, max, 4);
  const domain: [number, number] = [0, Math.max(max, yTicks[yTicks.length - 1])];
  const cell = (v: number | null) => (v === null ? "–" : usd(v));
  return (
    <section className="card">
      <div className="card-head">
        <h2>Dollars and euros in cross-border banking, {periodLabel(banks.periods[end])}</h2>
      </div>
      <p className="muted">
        Banks worldwide have {cell(offshore[end])} of dollar claims on residents outside the United States, out of {cell(world[end])} of
        cross-border dollar claims in all.
      </p>
      <div className="tables">
        <div className="scroll-x">
          <table className="table">
            <thead>
              <tr>
                <th>Banks' cross-border claims on residents of</th>
                <th className="num">All currencies</th>
                <th className="num">In US dollars</th>
                <th className="num">In euro</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(banks.areas).map(([id, block]) => (
                <tr key={id} className={id === "world" ? "total" : undefined}>
                  <td>
                    {AREA_COLOR[id] && <span className="swatch" style={{ background: AREA_COLOR[id] }} />} {name(id)}
                  </td>
                  <td className="num">{cell(block.claims.all[end])}</td>
                  <td className="num">{cell(block.claims.usd[end])}</td>
                  <td className="num">{cell(block.claims.eur[end])}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <figure>
          <figcaption>Dollar claims of banks on residents outside the United States</figcaption>
          <Chart
            periods={banks.periods}
            start={Math.max(0, start)}
            end={end}
            domain={domain}
            yTicks={yTicks}
            formatY={(v) => axisUsd(v, domain[1])}
            height={230}
            period={-1}
            onPeriod={() => {}}
            events={[]}
            ariaLabel="Dollar claims of banks worldwide on residents outside the United States, over time"
            tooltip={(i) => (offshore[i] === null ? [] : [{ key: "offshore", label: "dollar claims outside the US", value: usd(offshore[i]!), color: "var(--s1)" }])}
          >
            {({ x, y }) => {
              const points = offshore.flatMap((v, i) => (v === null ? [] : [`${x(i)},${y(v)}`]));
              return (
                <>
                  <path d={`M${x(Math.max(0, start))},${y(0)} L${points.join(" L")} L${x(end)},${y(0)} Z`} fill="var(--s1)" opacity={0.1} />
                  <path d={`M${points.join(" L")}`} fill="none" stroke="var(--s1)" strokeWidth={2} strokeLinejoin="round" />
                </>
              );
            }}
          </Chart>
        </figure>
      </div>
      <p className="muted small">{data.notes.all_banks}</p>
    </section>
  );
}
