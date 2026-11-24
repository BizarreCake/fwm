import { useState } from "react";
import { fit } from "./FlowDiagram";
import { TimeBar, useTimeControls } from "./time";
import type { Family, SideName, SystemMapView } from "./types";
import { useFetch } from "./useFetch";
import { api, base, color, periodLabel, usd, useWidth } from "./util";

type Scope = "debt" | "all";
type Focus =
  | { kind: "group"; id: string }
  | { kind: "family"; id: string }
  | { kind: "band"; side: SideName; group: string; family: string };

const HEIGHT = 640;
const TOP = 20;
const GAP = 8;
const MIN_SLOT = 18;
const NODE = 12;

export function SystemMapCard() {
  const { data, error } = useFetch<SystemMapView>(api("system-map"));
  if (error) return <section className="card"><p className="muted">Could not load the system map: {error}</p></section>;
  if (!data) return <section className="card"><p className="muted">Loading the system map…</p></section>;
  return <SystemMap view={data} />;
}

const at = (values: number[] | undefined, period: number) => Math.max(0, values?.[period] ?? 0);

interface Slot {
  id: string;
  value: number;
  top: number;
  height: number;
  mid: number;
}

/** Stack nodes down a column, each in a slot tall enough for its label, centred vertically. */
function column(items: { id: string; value: number }[], scale: number, available: number): Map<string, Slot> {
  const slots = items.map((item) => Math.max(item.value * scale, MIN_SLOT));
  const used = slots.reduce((a, b) => a + b, 0) + GAP * Math.max(0, items.length - 1);
  let y = TOP + Math.max(0, (available - used) / 2);
  const out = new Map<string, Slot>();
  items.forEach((item, i) => {
    const height = item.value * scale;
    out.set(item.id, { id: item.id, value: item.value, top: y + (slots[i] - height) / 2, height, mid: y + slots[i] / 2 });
    y += slots[i] + GAP;
  });
  return out;
}

function SystemMap({ view }: { view: SystemMapView }) {
  const time = useTimeControls(view.periods);
  const period = time.period;
  const [scope, setScope] = useState<Scope>("debt");
  const [hover, setHover] = useState<Focus | null>(null);
  const [pinned, setPinned] = useState<Focus | null>(null);
  const [ref, width] = useWidth<HTMLDivElement>();

  const families = view.families.filter((f) => scope === "all" || f.debt_like);
  const groupName = new Map(view.groups.map((g) => [g.id, g.name]));
  const owedBy = (g: string) => families.reduce((sum, f) => sum + at(f.issuers[g], period), 0);
  const heldBy = (g: string) => families.reduce((sum, f) => sum + at(f.holders[g], period), 0);
  const owedOf = (f: Family) => view.groups.reduce((sum, g) => sum + at(f.issuers[g.id], period), 0);
  const heldOf = (f: Family) => view.groups.reduce((sum, g) => sum + at(f.holders[g.id], period), 0);

  const left = view.groups.map((g) => ({ id: g.id, value: owedBy(g.id) })).filter((n) => n.value > 0);
  const right = view.groups.map((g) => ({ id: g.id, value: heldBy(g.id) })).filter((n) => n.value > 0);
  const middle = families.map((f) => ({ id: f.id, value: Math.max(owedOf(f), heldOf(f)) }));

  const available = HEIGHT - TOP;
  const scale = Math.min(...[left, middle, right].map((items) => fit(items.map((n) => n.value), available, MIN_SLOT, GAP)));
  const leftSlots = column(left, scale, available);
  const middleSlots = column(middle, scale, available);
  const rightSlots = column(right, scale, available);

  const wide = width >= 820;
  const labelWidth = wide ? 250 : Math.min(120, width * 0.22);
  const xLeft = labelWidth;
  const xRight = Math.max(xLeft + 160, width - labelWidth - NODE);
  const xMiddle = (xLeft + NODE + xRight) / 2 - NODE / 2;

  const focus = pinned ?? hover;
  const lit = (side: SideName, group: string, family: string) => {
    if (!focus) return null;
    if (focus.kind === "group") return focus.id === group;
    if (focus.kind === "family") return focus.id === family;
    return focus.side === side && focus.group === group && focus.family === family;
  };
  const toggle = (next: Focus) => setPinned(pinned && JSON.stringify(pinned) === JSON.stringify(next) ? null : next);

  const ribbon = (x0: number, y0: number, x1: number, y1: number, h: number) => {
    const mid = (x0 + x1) / 2;
    return `M${x0},${y0} C${mid},${y0} ${mid},${y1} ${x1},${y1} L${x1},${y1 + h} C${mid},${y1 + h} ${mid},${y0 + h} ${x0},${y0 + h} Z`;
  };

  // Bands: walk groups then families so each node's bands stack in a stable order.
  const bands: { key: string; side: SideName; group: string; family: string; value: number; path: string }[] = [];
  const build = (side: SideName, nodes: Map<string, Slot>) => {
    const groupOffset = new Map<string, number>();
    const familyOffset = new Map<string, number>();
    for (const group of view.groups) {
      const node = nodes.get(group.id);
      if (!node) continue;
      for (const family of families) {
        const value = at((side === "issuers" ? family.issuers : family.holders)[group.id], period);
        const h = value * scale;
        if (h < 0.3) continue;
        const target = middleSlots.get(family.id)!;
        const yGroup = node.top + (groupOffset.get(group.id) ?? 0);
        const yFamily = target.top + (familyOffset.get(family.id) ?? 0);
        groupOffset.set(group.id, (groupOffset.get(group.id) ?? 0) + h);
        familyOffset.set(family.id, (familyOffset.get(family.id) ?? 0) + h);
        const path = side === "issuers" ? ribbon(xLeft + NODE, yGroup, xMiddle, yFamily, h) : ribbon(xMiddle + NODE, yFamily, xRight, yGroup, h);
        bands.push({ key: `${side}-${group.id}-${family.id}`, side, group: group.id, family: family.id, value, path });
      }
    }
  };
  build("issuers", leftSlots);
  build("holders", rightSlots);

  let readout = "Hover a sector group or an instrument to trace it; click to keep it highlighted.";
  let readoutLink: Family | null = null;
  if (focus?.kind === "group") {
    readout = `${groupName.get(focus.id)}: owes ${usd(owedBy(focus.id))}, holds ${usd(heldBy(focus.id))} of the instruments shown.`;
  } else if (focus?.kind === "family") {
    const family = families.find((f) => f.id === focus.id);
    if (family) {
      readout = `${family.name}: ${usd(owedOf(family))} owed, ${usd(heldOf(family))} held.`;
      readoutLink = family;
    }
  } else if (focus?.kind === "band") {
    const family = families.find((f) => f.id === focus.family);
    if (family) {
      const amount = at((focus.side === "issuers" ? family.issuers : family.holders)[focus.group], period);
      readout = `${groupName.get(focus.group)} ${focus.side === "issuers" ? "owe" : "hold"} ${usd(amount)} of ${family.name.toLowerCase()}.`;
      readoutLink = family;
    }
  }

  const groupNodes = (side: SideName, nodes: Map<string, Slot>) =>
    [...nodes.values()].map((node) => {
      const isLeft = side === "issuers";
      const on = focus?.kind === "group" && focus.id === node.id;
      return (
        <g
          key={`${side}-${node.id}`}
          className="flow-band"
          tabIndex={0}
          role="button"
          aria-pressed={pinned?.kind === "group" && pinned.id === node.id}
          aria-label={`${groupName.get(node.id)}: ${isLeft ? "owes" : "holds"} ${usd(node.value)}`}
          onPointerEnter={() => setHover({ kind: "group", id: node.id })}
          onPointerLeave={() => setHover(null)}
          onFocus={() => setHover({ kind: "group", id: node.id })}
          onBlur={() => setHover(null)}
          onClick={() => toggle({ kind: "group", id: node.id })}
          onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && toggle({ kind: "group", id: node.id })}
        >
          <rect x={isLeft ? 0 : xRight} y={node.mid - 12} width={labelWidth + NODE} height={24} fill="transparent" />
          <rect x={isLeft ? xLeft : xRight} y={node.top} width={NODE} height={Math.max(node.height, 1)} rx={2} fill={color(node.id)} />
          <text
            x={isLeft ? xLeft - 8 : xRight + NODE + 8}
            y={node.mid}
            textAnchor={isLeft ? "end" : "start"}
            dominantBaseline="central"
            className={on ? "flow-label on" : "flow-label"}
          >
            {wide ? groupName.get(node.id) : ""}
            <tspan className="flow-share" dx={wide ? 6 : 0}>
              {usd(node.value)}
            </tspan>
          </text>
        </g>
      );
    });

  return (
    <section className="card">
      <div className="card-head">
        <h2>Who owes, through what, and who holds, {periodLabel(view.periods[period])}</h2>
        <div className="segmented" role="group" aria-label="Instruments shown">
          <button aria-pressed={scope === "debt"} onClick={() => setScope("debt")}>
            Debt, loans &amp; deposits
          </button>
          <button aria-pressed={scope === "all"} onClick={() => setScope("all")}>
            Everything
          </button>
        </div>
      </div>
      <TimeBar time={time} />
      <p className="muted readout" aria-live="polite">
        {readout} {readoutLink && <a href={`${base()}/instrument/${readoutLink.instrument_id}`}>Open {readoutLink.name.toLowerCase()} →</a>}
      </p>
      <div ref={ref} className="flow">
        {width > 0 && (
          <svg width={width} height={HEIGHT} role="img" aria-label="Amounts owed and held, by sector group and instrument">
            <text x={xLeft + NODE} y={10} textAnchor="end" className="flow-side">
              Owed by
            </text>
            <text x={xRight} y={10} className="flow-side">
              Held by
            </text>
            {bands.map((band) => {
              const state = lit(band.side, band.group, band.family);
              return (
                <path
                  key={band.key}
                  d={band.path}
                  fill={color(band.group)}
                  opacity={state === null ? 0.32 : state ? 0.7 : 0.07}
                  onPointerEnter={() => setHover({ kind: "band", side: band.side, group: band.group, family: band.family })}
                  onPointerLeave={() => setHover(null)}
                />
              );
            })}
            {groupNodes("issuers", leftSlots)}
            {groupNodes("holders", rightSlots)}
            {families.map((family) => {
              const node = middleSlots.get(family.id)!;
              const on = focus?.kind === "family" && focus.id === family.id;
              return (
                <g
                  key={family.id}
                  className="flow-band"
                  tabIndex={0}
                  role="button"
                  aria-pressed={pinned?.kind === "family" && pinned.id === family.id}
                  aria-label={`${family.name}: ${usd(owedOf(family))} owed, ${usd(heldOf(family))} held`}
                  onPointerEnter={() => setHover({ kind: "family", id: family.id })}
                  onPointerLeave={() => setHover(null)}
                  onFocus={() => setHover({ kind: "family", id: family.id })}
                  onBlur={() => setHover(null)}
                  onClick={() => toggle({ kind: "family", id: family.id })}
                  onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && toggle({ kind: "family", id: family.id })}
                >
                  <rect x={xMiddle - 70} y={node.mid - 10} width={NODE + 140} height={20} fill="transparent" />
                  <rect x={xMiddle} y={node.top} width={NODE} height={Math.max(node.height, 1)} rx={2} fill="var(--text-secondary)" />
                  <text x={xMiddle + NODE / 2} y={node.mid} textAnchor="middle" dominantBaseline="central" className={on ? "map-family on" : "map-family"}>
                    {family.name}
                  </text>
                </g>
              );
            })}
          </svg>
        )}
      </div>
      <details className="map-table">
        <summary>Show as a table</summary>
        {(["issuers", "holders"] as SideName[]).map((side) => (
          <div className="scroll-x" key={side}>
            <table className="table">
              <caption>{side === "issuers" ? "Owed by" : "Held by"}, {periodLabel(view.periods[period])}</caption>
              <thead>
                <tr>
                  <th>Instrument</th>
                  {view.groups.map((g) => (
                    <th key={g.id} className="num">
                      <span className="swatch" style={{ background: color(g.id) }} /> {g.name}
                    </th>
                  ))}
                  <th className="num">Total</th>
                </tr>
              </thead>
              <tbody>
                {families.map((family) => (
                  <tr key={family.id}>
                    <td>
                      <a href={`${base()}/instrument/${family.instrument_id}`}>{family.name}</a>
                    </td>
                    {view.groups.map((g) => (
                      <td key={g.id} className="num">
                        {usd(at((side === "issuers" ? family.issuers : family.holders)[g.id], period))}
                      </td>
                    ))}
                    <td className="num strong">{usd(side === "issuers" ? owedOf(family) : heldOf(family))}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
      </details>
      <p className="muted small">
        {view.notes.reading} {view.notes.sides} {view.notes.coverage}
      </p>
    </section>
  );
}
