import { useEffect, useState } from "react";
import { SectorPage } from "./SectorPage";
import { InstrumentPage } from "./InstrumentPage";

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

/** Treasury securities: the page the app opens on. */
const HOME_INSTRUMENT = "F3_2";

export function App() {
  const hash = useHash();
  const sector = hash.match(/^#\/sector\/([\w]+)$/);
  if (sector) return <SectorPage key={sector[1]} sectorId={sector[1]} />;
  const instrument = hash.match(/^#\/instrument\/([\w]+)$/);
  const instrumentId = instrument ? instrument[1] : HOME_INSTRUMENT;
  return <InstrumentPage key={instrumentId} instrumentId={instrumentId} />;
}
