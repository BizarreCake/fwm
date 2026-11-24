import type { Group } from "./types";
import { color, pct, useWidth } from "./util";

interface Props {
  groups: Group[];
  period: number;
  selected: string;
  onSelect: (id: string) => void;
}

const HEIGHT = 380;
const GAP = 6;
const MIN_SLOT = 20;
const NODE = 12;
const LABEL_WIDTH = 220;

/** Issuer on the left, holder groups on the right; band width = share of holdings. */
export function FlowDiagram({ groups, period, selected, onSelect }: Props) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const values = groups.map((g) => Math.max(0, g.level[period]));
  const total = values.reduce((a, b) => a + b, 0) || 1;
  const shares = values.map((v) => v / total);

  // Each holder gets a slot at least MIN_SLOT tall so labels never collide;
  // the band itself keeps its true proportional height.
  const available = HEIGHT - GAP * (groups.length - 1);
  let scale = available;
  for (let pass = 0; pass < 4; pass++) {
    const small = shares.filter((s) => s * scale < MIN_SLOT);
    const smallShare = small.reduce((a, b) => a + b, 0);
    scale = (available - small.length * MIN_SLOT) / (1 - smallShare || 1);
  }

  const right = Math.max(120, width - LABEL_WIDTH);
  let sourceY = (HEIGHT - scale) / 2;
  let slotY = 0;
  const bands = groups.map((group, i) => {
    const height = shares[i] * scale;
    const slot = Math.max(height, MIN_SLOT);
    const band = { group, share: shares[i], height, sourceY, targetY: slotY + (slot - height) / 2, slotY, slot };
    sourceY += height;
    slotY += slot + GAP;
    return band;
  });

  const mid = (NODE + right) / 2;

  return (
    <div ref={ref} className="flow">
      {width > 0 && (
        <svg width={width} height={HEIGHT} role="img" aria-label="Share of Treasury securities held by each holder group">
          <rect x={0} y={(HEIGHT - scale) / 2} width={NODE} height={scale} rx={2} fill="var(--text-secondary)" />
          {bands.map(({ group, share, height, sourceY, targetY, slotY, slot }) => {
            const dim = selected !== group.id;
            const ribbon =
              `M${NODE},${sourceY} C${mid},${sourceY} ${mid},${targetY} ${right},${targetY} ` +
              `L${right},${targetY + height} C${mid},${targetY + height} ${mid},${sourceY + height} ${NODE},${sourceY + height} Z`;
            return (
              <g
                key={group.id}
                className="flow-band"
                tabIndex={0}
                role="button"
                aria-pressed={!dim}
                aria-label={`${group.name}, ${pct(share)}`}
                onClick={() => onSelect(group.id)}
                onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && onSelect(group.id)}
              >
                <rect x={NODE} y={slotY} width={width - NODE} height={slot} fill="transparent" />
                {height > 0.25 && <path d={ribbon} fill={color(group.id)} opacity={dim ? 0.28 : 0.6} />}
                <rect
                  x={right}
                  y={targetY}
                  width={NODE}
                  height={Math.max(height, 1)}
                  rx={2}
                  fill={color(group.id)}
                />
                <text x={right + NODE + 8} y={slotY + slot / 2} dominantBaseline="central" className={dim ? "flow-label" : "flow-label on"}>
                  {group.name}
                  <tspan className="flow-share" dx={6}>
                    {pct(share)}
                  </tspan>
                </text>
              </g>
            );
          })}
        </svg>
      )}
    </div>
  );
}
