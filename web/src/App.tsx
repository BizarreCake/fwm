import { useEffect, useState } from "react";
import { SectorPage } from "./SectorPage";
import { InstrumentPage } from "./InstrumentPage";
import { OverviewPage } from "./OverviewPage";
import { WeeklyFedPage } from "./WeeklyFedPage";
import { ForeignPage } from "./ForeignPage";
import { CountryPage } from "./CountryPage";
import { EconomyPage } from "./EconomyPage";
import { setEconomy } from "./util";
import { Chat } from "./Chat";
import { ContextProvider } from "./context";

function useHash(): string {
  const [hash, setHash] = useState(window.location.hash);
  useEffect(() => {
    const onChange = () => {
      setHash(window.location.hash);
      window.scrollTo(0, 0);
    };
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return hash;
}

export function App() {
  return (
    <ContextProvider>
      <Route />
      <Chat />
    </ContextProvider>
  );
}

// Pages about one economy's own accounts carry its id: #/us/sector/S121, #/ea/sector/S1M.
const ECONOMY = "us";
const ECONOMIES = ["us", "ea"];

function Route() {
  const hash = useHash();
  const [path, query = ""] = hash.split("?");
  // Links made before pages carried an economy (#/sector/S121) still work.
  const legacy = path.match(/^#\/(sector|instrument|foreign|weekly)\/(.+)$/);
  useEffect(() => {
    if (legacy) window.location.replace(`#/${ECONOMY}/${legacy[1]}/${legacy[2]}${query ? `?${query}` : ""}`);
  }, [legacy, query]);
  if (legacy) return null;
  // A link may name the period to show, e.g. #/us/instrument/F3_2?period=2022:Q1
  const period = new URLSearchParams(query).get("period") ?? undefined;
  // The economy decides the currency, API paths and link prefix for whatever renders below.
  const named = path.match(/^#\/(\w+)(?:\/|$)/)?.[1];
  const current = named && ECONOMIES.includes(named) ? named : ECONOMY;
  setEconomy(current);
  const country = path.match(/^#\/country\/([\w-]+)$/);
  if (country) return <CountryPage key={country[1]} countryId={country[1]} period={period} />;
  const page = path.match(/^#\/(\w+)\/(\w+)\/([\w]+)$/);
  if (page && page[1] === current) {
    const [, , kind, id] = page;
    if (kind === "sector") return <SectorPage key={`${current}/${id}`} sectorId={id} period={period} />;
    if (kind === "instrument") return <InstrumentPage key={`${current}/${id}`} instrumentId={id} period={period} />;
  }
  if (page && page[1] === ECONOMY) {
    const [, , kind, id] = page;
    if (kind === "foreign") return <ForeignPage key={id} asset={id} period={period} />;
    if (kind === "weekly" && id === "fed") return <WeeklyFedPage period={period} />;
  }
  if (current !== ECONOMY) return <EconomyPage key={current} />;
  return <OverviewPage />;
}
