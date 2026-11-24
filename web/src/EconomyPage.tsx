import type { InstrumentSummary, SectorSummary } from "./types";
import { useFetch } from "./useFetch";
import { api, base, economies, economy, economyName, periodLabel, usd } from "./util";

interface EconomyInfo {
  id: string;
  name: string;
  currency: string;
  accounts: string;
  loaded: boolean;
}

/** Switch between the economies that have full accounts. */
export function EconomySwitch() {
  return (
    <div className="segmented" role="group" aria-label="Economy">
      {economies().map((e) => (
        <button key={e.id} aria-pressed={e.id === economy()} onClick={() => (window.location.hash = e.id === "us" ? "#/" : `#/${e.id}`)}>
          {e.name}
        </button>
      ))}
    </div>
  );
}

/** The front page of an economy that has sector accounts but not yet the US page's map and rankings. */
export function EconomyPage() {
  const sectors = useFetch<SectorSummary[]>(api("sectors"));
  const instruments = useFetch<InstrumentSummary[]>(api("instruments"));
  const info = useFetch<EconomyInfo[]>("/api/economies").data?.find((e) => e.id === economy());
  // Any sector's view carries the list of quarters; the smallest is enough to learn the latest one.
  const latest = useFetch<{ periods: string[] }>(api("sectors/S129")).data?.periods.at(-1);
  const error = sectors.error ?? instruments.error;
  if (error) return <main className="page"><p>Could not load the {economyName()} accounts: {error}</p></main>;
  if (!sectors.data || !instruments.data) return <main className="page"><p className="muted">Loading…</p></main>;

  const whole = sectors.data.filter((s) => !s.part_of);
  const resident = whole.filter((s) => s.id !== "ROW");
  const assets = resident.reduce((sum, s) => sum + (s.total_assets ?? 0), 0);
  const liabilities = resident.reduce((sum, s) => sum + (s.total_liabilities ?? 0), 0);
  const world = sectors.data.find((s) => s.id === "ROW");

  return (
    <main className="page">
      <header className="header">
        <div>
          <h1>
            {economyName()} financial system{latest ? `, ${periodLabel(latest)}` : ""}
          </h1>
          <p className="muted">
            Every sector's financial balance sheet, and who holds and who owes each instrument. {info?.accounts}. Amounts are in{" "}
            {info?.currency === "EUR" ? "euro" : info?.currency}; nothing is converted.
          </p>
        </div>
        <EconomySwitch />
      </header>

      <section className="card">
        <div className="tiles">
          <div className="tile">
            <div className="muted">Financial assets of residents</div>
            <div className="tile-value">{usd(assets)}</div>
            <div className="muted">all sectors, not consolidated</div>
          </div>
          <div className="tile">
            <div className="muted">Liabilities of residents</div>
            <div className="tile-value">{usd(liabilities)}</div>
            <div className="muted">including equity issued</div>
          </div>
          {world && (
            <div className="tile">
              <div className="muted">Held by the rest of the world</div>
              <div className="tile-value">{usd(world.total_assets ?? 0)}</div>
              <div className="muted">residents hold {usd(world.total_liabilities ?? 0)} abroad</div>
            </div>
          )}
        </div>
      </section>

      <section className="card tables">
        <div className="scroll-x">
          <table className="table">
            <caption>Sectors{latest ? `, ${periodLabel(latest)}` : ""}</caption>
            <thead>
              <tr>
                <th>Sector</th>
                <th className="num">Financial assets</th>
                <th className="num">Liabilities</th>
              </tr>
            </thead>
            <tbody>
              {sectors.data.map((s) => (
                <tr key={s.id}>
                  <td style={{ paddingLeft: s.part_of ? 28 : undefined }}>
                    {s.part_of && <span className="muted">of which: </span>}
                    <a href={`${base()}/sector/${s.id}`}>{s.name}</a>
                  </td>
                  <td className="num">{s.total_assets == null ? "n/a" : usd(s.total_assets)}</td>
                  <td className="num">{s.total_liabilities == null ? "n/a" : usd(s.total_liabilities)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="scroll-x">
          <table className="table">
            <caption>Instruments{latest ? `, ${periodLabel(latest)}` : ""}</caption>
            <thead>
              <tr>
                <th>Instrument</th>
                <th className="num">Held</th>
              </tr>
            </thead>
            <tbody>
              {instruments.data.map((i) => (
                <tr key={i.id}>
                  <td>
                    <a href={`${base()}/instrument/${i.id}`}>{i.name}</a>
                  </td>
                  <td className="num">{i.holders_total == null ? "n/a" : usd(i.holders_total)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <footer className="footer muted">
        <p>
          Not yet built for this economy: the system map, the ranking of unusual flows, interest rates and central bank announcements,
          amounts as a share of GDP, and the assistant's weekly and country tools. Those exist for the United States only.
        </p>
        <p>
          Banks, central banks and money market funds are one sector here; central banks are published separately from 2015. The rest of
          the world is read from the euro area's positions against non-residents.
        </p>
      </footer>
    </main>
  );
}
