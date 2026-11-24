import { useState } from "react";
import type { CompareMeasures, CompareView } from "./types";
import { useFetch } from "./useFetch";
import { money, periodLabel } from "./util";

type Unit = "pct_of_gdp" | "usd";

// Colour follows the economy, here and anywhere else two economies share a chart.
const ECONOMY_COLOR: Record<string, string> = { us: "var(--s1)", ea: "var(--s2)" };

/** The economies side by side: as a share of each one's GDP, or in dollars. */
export function CompareCard() {
  const { data } = useFetch<CompareView>("/api/compare");
  const [unit, setUnit] = useState<Unit>("pct_of_gdp");
  if (!data) return null;
  const last = data.periods.length - 1;
  const format = (value: number | null) => (value === null ? "–" : unit === "usd" ? money(value, "$") : `${Math.round(value)}%`);
  const at = (measures: CompareMeasures) => measures[unit][last];

  const section = (title: string, rows: CompareView["instruments"]) => {
    const max = Math.max(1, ...rows.flatMap((row) => data.economies.map((e) => at(row[e.id]) ?? 0)));
    return (
      <div className="scroll-x">
        <table className="table compare">
          <thead>
            <tr>
              <th>{title}</th>
              {data.economies.map((e) => (
                <th key={e.id} className="num">
                  <span className="swatch" style={{ background: ECONOMY_COLOR[e.id] }} /> {e.name}
                </th>
              ))}
              <th aria-hidden="true" />
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id}>
                <td>{row.name}</td>
                {data.economies.map((e) => (
                  <td key={e.id} className="num">
                    {format(at(row[e.id]))}
                  </td>
                ))}
                <td className="compare-bars" aria-hidden="true">
                  {data.economies.map((e) => (
                    <div
                      key={e.id}
                      className="compare-bar"
                      title={`${e.name}: ${format(at(row[e.id]))}`}
                      style={{ width: `${(100 * Math.max(0, at(row[e.id]) ?? 0)) / max}%`, background: ECONOMY_COLOR[e.id] }}
                    />
                  ))}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  };

  return (
    <section className="card">
      <div className="card-head">
        <h2>United States and euro area side by side, {periodLabel(data.periods[last])}</h2>
        <div className="segmented" role="group" aria-label="Unit for comparing economies">
          <button aria-pressed={unit === "pct_of_gdp"} onClick={() => setUnit("pct_of_gdp")}>
            % of own GDP
          </button>
          <button aria-pressed={unit === "usd"} onClick={() => setUnit("usd")}>
            US dollars
          </button>
        </div>
      </div>
      <p className="muted">
        GDP over the past four quarters: {data.economies.map((e) => `${e.name} ${money(data.gdp[e.id].usd[last] ?? 0, "$")}`).join(", ")}
        {data.usd_per_eur[last] !== null && ` (at $${data.usd_per_eur[last]!.toFixed(2)} per euro)`}.
      </p>
      <div className="tables">
        {section("Outstanding, by instrument", data.instruments)}
        {section("Held by", data.holders)}
      </div>
      <p>
        <a href="#/links?pair=us-ea">What each holds of the other, and links with other economies →</a>
      </p>
      <p className="muted small">
        {data.notes.what_it_is} {data.notes.conversion} {data.notes.matching}
      </p>
    </section>
  );
}
