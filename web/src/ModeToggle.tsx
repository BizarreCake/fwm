import { currencyName } from "./util";
import { useContextData } from "./context";
import type { Mode } from "./types";

export function ModeToggle({ mode, onChange, gdp = true }: { mode: Mode; onChange: (mode: Mode) => void; gdp?: boolean }) {
  const context = useContextData();
  return (
    <div className="segmented" role="group" aria-label="Scale">
      <button aria-pressed={mode === "usd"} onClick={() => onChange("usd")}>
        {currencyName()}
      </button>
      <button aria-pressed={mode === "share"} onClick={() => onChange("share")}>
        Share
      </button>
      {gdp && context && (
        <button aria-pressed={mode === "gdp"} title={context.notes.gdp} onClick={() => onChange("gdp")}>
          % of GDP
        </button>
      )}
    </div>
  );
}
