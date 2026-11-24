import { economies, economy } from "./util";

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
