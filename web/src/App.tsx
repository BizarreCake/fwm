import { useEffect, useState } from "react";
import { SectorPage } from "./SectorPage";
import { TreasuryPage } from "./TreasuryPage";

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
  const hash = useHash();
  const sector = hash.match(/^#\/sector\/([\w]+)$/);
  if (sector) return <SectorPage key={sector[1]} sectorId={sector[1]} />;
  return <TreasuryPage />;
}
