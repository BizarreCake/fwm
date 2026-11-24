import { SystemMapCard } from "./SystemMap";
import { EconomySwitch } from "./EconomyPage";
import { CompareCard } from "./CompareCard";
import { WeeklyStrip } from "./WeeklyFedPage";
import { CountriesCard } from "./CountryPage";
import type { Move, Overview } from "./types";
import { useFetch } from "./useFetch";
import { api, base, color, economy, economyName, periodLabel, usd } from "./util";

export function OverviewPage() {
  const { data, error } = useFetch<Overview>(api("overview"));
  if (error) return <main className="page"><p>Could not load the overview: {error}</p></main>;
  if (!data) return <main className="page"><p className="muted">Loading…</p></main>;
  const quarter = periodLabel(data.period);
  const us = economy() === "us";

  return (
    <main className="page">
      <header className="header">
        <div>
          <h1>{us ? "US" : economyName()} financial system, {quarter}</h1>
          <p className="muted">
            The whole system on one page, what moved in the latest quarter, and where to look next.
            {!us && " Amounts are in euro; nothing is converted."}
          </p>
        </div>
        <EconomySwitch />
      </header>

      <WeeklyStrip />

      <SystemMapCard />

      <CompareCard />

      <section className="card">
        <div className="card-head">
          <h2>Unusual flows</h2>
          <p className="muted">Net transactions far outside that position's own ten-year norm, largest first.</p>
        </div>
        <Moves moves={data.unusual_flows} kind="flow" now={data.period} from={data.unusual_flows[0]?.history_from} />
      </section>

      <section className="card">
        <div className="card-head">
          <h2>Largest flows</h2>
          <p className="muted">Net transactions by size, unusual or not.</p>
        </div>
        <Moves moves={data.largest_flows} kind="flow" now={data.period} from={data.largest_flows[0]?.history_from} />
      </section>

      <section className="card">
        <div className="card-head">
          <h2>Largest valuation changes</h2>
          <p className="muted">Changes in holdings that were not transactions: mostly price moves.</p>
        </div>
        <Moves moves={data.valuation_changes} kind="valuation" now={data.period} from={data.valuation_changes[0]?.history_from} />
      </section>

      {us && <CountriesCard />}

      <section className="card tables">
        <div className="scroll-x">
          <table className="table">
            <caption>Instruments, {quarter}</caption>
            <thead>
              <tr>
                <th>Instrument</th>
                <th className="num">Held</th>
                <th className="num">Net transactions</th>
              </tr>
            </thead>
            <tbody>
              {data.instruments.map((i) => (
                <tr key={i.id}>
                  <td>
                    <a href={`${base()}/instrument/${i.id}`}>{i.name}</a>
                    {i.composite && <span className="basis"> total of the tables below it</span>}
                  </td>
                  <td className="num">{i.held === null ? "–" : usd(i.held)}</td>
                  <td className="num">{i.transactions === null ? "–" : usd(i.transactions, true)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="scroll-x">
          <table className="table">
            <caption>Sectors, {quarter}</caption>
            <thead>
              <tr>
                <th>Sector</th>
                <th className="num">Financial assets</th>
                <th className="num">Liabilities</th>
              </tr>
            </thead>
            <tbody>
              {data.sectors.map((s) => (
                <tr key={s.id}>
                  <td style={{ paddingLeft: s.part_of ? 28 : undefined }}>
                    {s.part_of && <span className="muted">of which: </span>}
                    <a href={`${base()}/sector/${s.id}`}>{s.name}</a>
                  </td>
                  <td className="num">{s.total_assets === null ? "–" : usd(s.total_assets)}</td>
                  <td className="num">{s.total_liabilities === null ? "–" : usd(s.total_liabilities)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <footer className="footer muted">
        <p>{data.notes.unusual}</p>
        <p>{data.notes.valuation}</p>
        <p>{data.notes.coverage}</p>
        {!us && (
          <p>
            Not built for the euro area: holdings by country. Euro amounts are converted to dollars only in the side-by-side card.
          </p>
        )}
      </footer>
    </main>
  );
}

function verb(move: Move, kind: "flow" | "valuation"): string {
  const up = move.amount > 0;
  if (kind === "valuation") return up ? "gained on" : "lost on";
  if (move.side === "holders") return up ? "added" : "reduced";
  return up ? "issued" : "paid down";
}

function quarterIndex(period: string): number {
  const [year, quarter] = period.split(":Q");
  return Number(year) * 4 + Number(quarter);
}

/** How long since a move this large; blank when it was within the past year, which says little. */
function context(move: Move, now: string): string {
  const direction = move.amount > 0 ? "increase" : "decrease";
  if (move.largest_since === null) return `Largest ${direction} on record`;
  if (quarterIndex(now) - quarterIndex(move.largest_since) < 4) return "";
  return `Largest ${direction} since ${periodLabel(move.largest_since)}`;
}

function Moves({ moves, kind, from, now }: { moves: Move[]; kind: "flow" | "valuation"; from?: string; now: string }) {
  if (!moves.length) return <p className="muted">Nothing met the threshold this quarter.</p>;
  return (
    <div className="scroll-x">
      <table className="table moves">
        <thead>
          <tr>
            <th>Sector</th>
            <th />
            <th>Instrument</th>
            <th className="num">Amount</th>
            <th>{from ? `Quarterly, since ${periodLabel(from)}` : "History"}</th>
            <th>Context</th>
          </tr>
        </thead>
        <tbody>
          {moves.map((move) => (
            <tr key={`${move.series}-${move.side}`}>
              <td>
                <span className="swatch" style={{ background: color(move.group) }} />{" "}
                {move.sector_id ? <a href={`${base()}/sector/${move.sector_id}`}>{move.sector}</a> : move.sector}
              </td>
              <td className="muted">{verb(move, kind)}</td>
              <td>
                <a href={`${base()}/instrument/${move.instrument_id}`}>{move.instrument}</a>
              </td>
              <td className="num strong">{usd(move.amount, true)}</td>
              <td>
                <Spark values={move.history} fill={color(move.group)} label={`${move.sector}, ${move.instrument}: quarterly history`} />
              </td>
              <td className="muted">{context(move, now)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const SPARK = { width: 132, height: 28 };

/** The position's recent quarters as bars around zero, the latest quarter in its group colour. */
function Spark({ values, fill, label }: { values: (number | null)[]; fill: string; label: string }) {
  const numbers = values.map((v) => v ?? 0);
  const max = Math.max(0, ...numbers);
  const min = Math.min(0, ...numbers);
  const span = max - min || 1;
  const step = SPARK.width / numbers.length;
  const y = (v: number) => ((max - v) / span) * SPARK.height;
  return (
    <svg width={SPARK.width} height={SPARK.height} role="img" aria-label={label} className="spark">
      <line x1={0} x2={SPARK.width} y1={y(0)} y2={y(0)} className="axis" />
      {numbers.map((v, i) => (
        <rect
          key={i}
          x={i * step}
          y={Math.min(y(v), y(0))}
          width={Math.max(1, step - 1)}
          height={Math.max(Math.abs(y(v) - y(0)), v === 0 ? 0 : 0.75)}
          fill={i === numbers.length - 1 ? fill : "var(--axis)"}
        />
      ))}
    </svg>
  );
}
