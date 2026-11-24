import type { Group, SideName } from "./types";
import { color, pct, useWidth } from "./util";

interface Props {
  name: string;
  issuers: Group[] | null;
  holders: Group[];
  period: number;
  selected: { side: SideName; id: string };
  onSelect: (side: SideName, id: string) => void;
}

const HEIGHT = 380;
const TOP = 18;
const GAP = 6;
const MIN_SLOT = 20;
const NODE = 12;

interface Band {
  group: Group;
  share: number;
  height: number;
  innerY: number;
  outerY: number;
  slotY: number;
  slot: number;
}

const value = (group: Group, period: number) => Math.max(0, group.level[period] ?? 0);

/** Largest pixels-per-unit at which a side fits, giving every group a slot tall enough for its label. */
function fit(values: number[], available: number): number {
  const total = values.reduce((a, b) => a + b, 0);
  if (!total) return 0;
  let scale = (available - GAP * (values.length - 1)) / total;
  for (let pass = 0; pass < 6; pass++) {
    const small = values.filter((v) => v * scale < MIN_SLOT);
    const rest = total - small.reduce((a, b) => a + b, 0);
    if (!rest) break;
    scale = (available - GAP * (values.length - 1) - small.length * MIN_SLOT) / rest;
  }
  return Math.max(0, scale);
}

function layout(groups: Group[], period: number, scale: number, available: number): Band[] {
  const values = groups.map((g) => value(g, period));
  const total = values.reduce((a, b) => a + b, 0) || 1;
  const slots = values.map((v) => Math.max(v * scale, MIN_SLOT));
  const used = slots.reduce((a, b) => a + b, 0) + GAP * (groups.length - 1);
  let slotY = TOP + (available - used) / 2;
  let innerY = TOP + (available - total * scale) / 2;
  return groups.map((group, i) => {
    const height = values[i] * scale;
    const band = { group, share: values[i] / total, height, innerY, outerY: slotY + (slots[i] - height) / 2, slotY, slot: slots[i] };
    innerY += height;
    slotY += slots[i] + GAP;
    return band;
  });
}

/**
 * Issuers on the left, holders on the right, the instrument in the middle. Both sides share one
 * scale, so a difference between what is owed and what is held shows as a difference in height.
 */
export function FlowDiagram({ name, issuers, holders, period, selected, onSelect }: Props) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const wide = width >= 760;
  const available = HEIGHT - TOP;
  const leftLabels = issuers ? (wide ? 250 : 0) : 0;
  const rightLabels = wide ? 220 : Math.min(235, width * 0.55);

  const sides = [holders, ...(issuers ? [issuers] : [])];
  const scale = Math.min(...sides.map((groups) => fit(groups.map((g) => value(g, period)), available)));
  const holderBands = layout(holders, period, scale, available);
  const issuerBands = issuers ? layout(issuers, period, scale, available) : [];

  const leftX = leftLabels;
  const rightX = Math.max(leftX + 120, width - rightLabels - NODE);
  const centerX = issuers ? (leftX + NODE + rightX) / 2 - NODE / 2 : 0;
  const total = (bands: Band[]) => bands.reduce((sum, b) => sum + b.height, 0);
  const centerHeight = Math.max(total(holderBands), total(issuerBands), 1);

  const ribbon = (x0: number, y0: number, x1: number, y1: number, h: number) => {
    const mid = (x0 + x1) / 2;
    return `M${x0},${y0} C${mid},${y0} ${mid},${y1} ${x1},${y1} L${x1},${y1 + h} C${mid},${y1 + h} ${mid},${y0 + h} ${x0},${y0 + h} Z`;
  };

  const side = (name: SideName, bands: Band[]) =>
    bands.map(({ group, share, height, innerY, outerY, slotY, slot }) => {
      const on = selected.side === name && selected.id === group.id;
      const left = name === "issuers";
      const nodeX = left ? leftX : rightX;
      const path = left
        ? ribbon(leftX + NODE, outerY, centerX, innerY, height)
        : ribbon(centerX + NODE, innerY, rightX, outerY, height);
      const showLabel = left ? leftLabels > 0 : true;
      return (
        <g
          key={`${name}-${group.id}`}
          className="flow-band"
          tabIndex={0}
          role="button"
          aria-pressed={on}
          aria-label={`${left ? "Issuer" : "Holder"}: ${group.name}, ${pct(share)}`}
          onClick={() => onSelect(name, group.id)}
          onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && onSelect(name, group.id)}
        >
          <rect
            x={left ? 0 : centerX + NODE}
            y={slotY}
            width={left ? centerX : width - centerX - NODE}
            height={slot}
            fill="transparent"
          />
          {height > 0.25 && <path d={path} fill={color(group.id)} opacity={on ? 0.6 : 0.28} />}
          <rect x={nodeX} y={outerY} width={NODE} height={Math.max(height, 1)} rx={2} fill={color(group.id)} />
          {showLabel && (
            <text
              x={left ? leftX - 8 : rightX + NODE + 8}
              y={slotY + slot / 2}
              textAnchor={left ? "end" : "start"}
              dominantBaseline="central"
              className={on ? "flow-label on" : "flow-label"}
            >
              {group.name}
              <tspan className="flow-share" dx={6}>
                {pct(share)}
              </tspan>
            </text>
          )}
        </g>
      );
    });

  return (
    <div ref={ref} className="flow">
      {width > 0 && (
        <svg width={width} height={HEIGHT} role="img" aria-label={`${name}: issuers and holders by sector group`}>
          {issuers && (
            <text x={wide ? leftX + NODE : 0} y={10} textAnchor={wide ? "end" : "start"} className="flow-side">
              Issuers
            </text>
          )}
          <text x={rightX} y={10} className="flow-side">
            Holders
          </text>
          {issuers && wide && (
            <text x={centerX + NODE / 2} y={10} textAnchor="middle" className="flow-center">
              {name}
            </text>
          )}
          <rect x={centerX} y={TOP + (available - centerHeight) / 2} width={NODE} height={centerHeight} rx={2} fill="var(--text-secondary)" />
          {side("issuers", issuerBands)}
          {side("holders", holderBands)}
        </svg>
      )}
    </div>
  );
}
