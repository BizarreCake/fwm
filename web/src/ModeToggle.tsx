import type { Mode } from "./types";

export function ModeToggle({ mode, onChange }: { mode: Mode; onChange: (mode: Mode) => void }) {
  return (
    <div className="segmented" role="group" aria-label="Scale">
      <button aria-pressed={mode === "usd"} onClick={() => onChange("usd")}>
        Dollars
      </button>
      <button aria-pressed={mode === "share"} onClick={() => onChange("share")}>
        Share
      </button>
    </div>
  );
}
