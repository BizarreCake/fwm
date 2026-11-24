import { useMemo, useState } from "react";
import { MeasureCharts } from "./MeasureCharts";
import { StackedChart, type StackSeries } from "./StackedChart";
import { TimeBar, useTimeControls } from "./time";
import { ModeToggle } from "./ModeToggle";
import type { Mode, SectorSummary, SectorView, SheetNode } from "./types";
import { useFetch } from "./useFetch";
import { pct, periodLabel, usd } from "./util";

type Side = "assets" | "liabilities";
const SLOTS = 7;
const OTHER = "var(--muted)";
const PARENT = "var(--text-secondary)";

/**
 * The lines worth telling apart at a glance: top-level lines, with any that are themselves
 * totals (e.g. "debt securities") replaced by their components.
 */
function displayItems(root: SheetNode): SheetNode[] {
  return root.children.flatMap((child) => (child.children.length ? child.children : [child]));
}

export function SectorPage({ sectorId }: { sectorId: string }) {
  const { data, error } = useFetch<SectorView>(`/api/sectors/${sectorId}`);
  if (error) {
    return (
      <main className="page">
        <a href="#/">← Overview</a>
        <p>Could not load this sector: {error}</p>
      </main>
    );
  }
  if (!data) return <main className="page"><p className="muted">Loading…</p></main>;
  return <Sector view={data} />;
}

/** Colour follows the line, not the selected quarter: the largest lines at the latest quarter get the slots. */
function assignColors(root: SheetNode | null): Map<string, string> {
  const colors = new Map<string, string>();
  if (!root) return colors;
  const last = root.level.length - 1;
  const items = displayItems(root);
  const ranked = [...items].sort((a, b) => Math.abs(b.level[last] ?? 0) - Math.abs(a.level[last] ?? 0));
  // The largest lines get a colour; slots are handed out in table order so that
  // neighbours in the stacked chart are neighbours in the (validated) palette order.
  const top = new Set(ranked.slice(0, SLOTS).map((node) => node.series));
  const slot = new Map(items.filter((node) => top.has(node.series)).map((node, i) => [node.series, `var(--s${i + 1})`]));
  const paint = (node: SheetNode, fill: string) => {
    colors.set(node.series, fill);
    [...node.children, ...node.memos].forEach((child) => paint(child, fill));
  };
  root.children.forEach((child) => child.children.length && colors.set(child.series, PARENT));
  items.forEach((item) => paint(item, slot.get(item.series) ?? OTHER));
  return colors;
}

function stackSeries(root: SheetNode, colors: Map<string, string>): StackSeries[] {
  const items = displayItems(root);
  const main = items.filter((c) => colors.get(c.series) !== OTHER);
  const rest = items.filter((c) => colors.get(c.series) === OTHER);
  const series: StackSeries[] = main.map((c) => ({ id: c.series, name: c.name, color: colors.get(c.series)!, values: c.level }));
  if (rest.length) {
    series.push({
      id: "other",
      name: rest.length === 1 ? rest[0].name : `Other (${rest.length} lines)`,
      color: OTHER,
      values: root.level.map((_, i) => rest.reduce((sum, c) => sum + (c.level[i] ?? 0), 0)),
    });
  }
  return series;
}

function index(root: SheetNode | null, into: Map<string, SheetNode>) {
  if (!root) return;
  into.set(root.series, root);
  [...root.children, ...root.memos].forEach((child) => index(child, into));
}

function Sector({ view }: { view: SectorView }) {
  const { periods, assets, liabilities, source, notes } = view;
  const time = useTimeControls(periods);
  const period = time.period;
  const sectors = useFetch<SectorSummary[]>("/api/sectors").data;

  const assetColors = useMemo(() => assignColors(assets), [assets]);
  const liabilityColors = useMemo(() => assignColors(liabilities), [liabilities]);
  const nodes = useMemo(() => {
    const map = new Map<string, SheetNode>();
    index(assets, map);
    index(liabilities, map);
    return map;
  }, [assets, liabilities]);

  const last = periods.length - 1;
  const largest = [...displayItems(assets)].sort((a, b) => (b.level[last] ?? 0) - (a.level[last] ?? 0))[0];
  const [selected, setSelected] = useState(largest.series);
  const [expanded, setExpanded] = useState<Set<string>>(
    () => new Set([...assets.children, ...(liabilities?.children ?? [])].filter((c) => c.children.length).map((c) => c.series)),
  );
  const [side, setSide] = useState<Side>("assets");
  const [mode, setMode] = useState<Mode>("usd");

  const node = nodes.get(selected) ?? largest;
  const fill = assetColors.get(node.series) ?? liabilityColors.get(node.series) ?? OTHER;
  const scale = Math.max(assets.level[period] ?? 0, liabilities?.level[period] ?? 0) || 1;
  const toggle = (series: string) => {
    const next = new Set(expanded);
    if (!next.delete(series)) next.add(series);
    setExpanded(next);
  };
  const stackRoot = side === "liabilities" && liabilities ? liabilities : assets;
  const stackColors = stackRoot === assets ? assetColors : liabilityColors;
  const stack = stackSeries(stackRoot, stackColors);
  const parts = [...node.children.map((c) => ({ c, memo: false })), ...node.memos.map((c) => ({ c, memo: true }))];

  const sheet = (root: SheetNode, colors: Map<string, string>, title: string) => (
    <div>
      <div className="sheet-head">
        <h2>{title}</h2>
        <span className="sheet-total">{usd(root.level[period] ?? 0)}</span>
      </div>
      <div className="sheet">
        <Rows
          nodes={root.children}
          depth={0}
          colors={colors}
          period={period}
          total={root.level[period] ?? 0}
          scale={scale}
          selected={selected}
          expanded={expanded}
          onSelect={setSelected}
          onToggle={toggle}
        />
      </div>
    </div>
  );

  return (
    <main className="page">
      <header className="header">
        <div>
          <a className="back" href="#/">
            ← Overview
          </a>
          <h1>{view.name}</h1>
          <p className="muted">
            Financial balance sheet, quarterly.{" "}
            {sectors && (
              <select
                className="picker"
                aria-label="Sector"
                value={view.id}
                onChange={(e) => (window.location.hash = `#/sector/${e.target.value}`)}
              >
                {sectors.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </select>
            )}
          </p>
        </div>
        <div className="hero">
          <div className="hero-value">{usd(assets.level[period] ?? 0)}</div>
          <div className="muted">
            total financial assets, {periodLabel(periods[period])}
            {liabilities && (
              <>
                <br />
                {usd(liabilities.level[period] ?? 0)} {liabilities.name.toLowerCase()}
              </>
            )}
          </div>
        </div>
      </header>

      <TimeBar time={time} />

      <section className={liabilities ? "card split even" : "card"}>
        {sheet(assets, assetColors, "Assets")}
        {liabilities ? sheet(liabilities, liabilityColors, liabilities.name) : <p className="muted">{notes.liabilities}</p>}
      </section>

      <section className="card">
        <div className="card-head">
          <h2>Composition over time</h2>
          <div className="controls">
            {liabilities && (
              <div className="segmented" role="group" aria-label="Side of the balance sheet">
                <button aria-pressed={side === "assets"} onClick={() => setSide("assets")}>
                  Assets
                </button>
                <button aria-pressed={side === "liabilities"} onClick={() => setSide("liabilities")}>
                  Liabilities
                </button>
              </div>
            )}
            <ModeToggle mode={mode} onChange={setMode} />
          </div>
        </div>
        <StackedChart
          series={stack}
          time={time}
          mode={mode}
          selected={stack.some((s) => s.id === selected) ? selected : undefined}
          ariaLabel={`${view.name}: composition of ${side} over time`}
        />
        <div className="legend-row">
          {stack.map((s) =>
            s.id === "other" ? (
              <span key={s.id} className="legend-item">
                <span className="swatch" style={{ background: s.color }} />
                {s.name}
              </span>
            ) : (
              <button key={s.id} className="row-button" aria-pressed={s.id === selected} onClick={() => setSelected(s.id)}>
                <span className="swatch" style={{ background: s.color }} />
                {s.name}
              </button>
            ),
          )}
        </div>
      </section>

      <section className="card">
        <div className="card-head">
          <h2>
            <span className="swatch" style={{ background: fill }} />
            {node.name}
          </h2>
          {node.instrument && <a href={`#/instrument/${node.instrument}`}>Who holds and owes this →</a>}
        </div>
        <MeasureCharts name={node.name} measures={node} fill={fill} time={time} />
        <div className="scroll-x">
          <table className="table">
            <caption>{periodLabel(periods[period])}</caption>
            <thead>
              <tr>
                <th>Line</th>
                <th className="num">Outstanding</th>
                <th className="num">Net transactions</th>
                <th className="num">Valuation &amp; other</th>
                <th>Z.1 series</th>
              </tr>
            </thead>
            <tbody>
              {[{ c: node, memo: false }, ...parts].map(({ c, memo }, i) => (
                <tr key={c.series} className={i === 0 && parts.length ? "total-row" : ""}>
                  <td>
                    {memo && <span className="basis">of which </span>}
                    {i === 0 ? c.name : (
                      <button className="link" onClick={() => setSelected(c.series)}>
                        {c.name}
                      </button>
                    )}
                  </td>
                  <td className="num">{c.level[period] === null ? "–" : usd(c.level[period]!)}</td>
                  <td className="num">{c.transactions[period] === null ? "–" : usd(c.transactions[period]!, true)}</td>
                  <td className="num">{c.other_change[period] === null ? "–" : usd(c.other_change[period]!, true)}</td>
                  <td className="series">
                    {c.series} <span className="basis">{c.basis === "market" ? "market value" : "book value"}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <footer className="footer muted">
        <p>
          Source: <a href={source.url}>{source.name}</a>, table {source.table}. Latest quarter {periodLabel(source.latest_period)}
          {source.published_at && <>; release published {source.published_at.slice(0, 10)}</>}.
        </p>
        <p>{notes.structure}</p>
        <p>{notes.other_change}</p>
      </footer>
    </main>
  );
}

interface RowsProps {
  nodes: SheetNode[];
  depth: number;
  colors: Map<string, string>;
  period: number;
  total: number;
  scale: number;
  selected: string;
  expanded: Set<string>;
  onSelect: (series: string) => void;
  onToggle: (series: string) => void;
}

function Rows(props: RowsProps) {
  const { nodes, depth, colors, period, total, scale, selected, expanded, onSelect, onToggle } = props;
  return (
    <>
      {nodes.map((node) => {
        const value = node.level[period] ?? 0;
        const open = expanded.has(node.series);
        const hasChildren = node.children.length > 0;
        return (
          <div key={node.series}>
            <div className={node.series === selected ? "sheet-row selected" : "sheet-row"} onClick={() => onSelect(node.series)}>
              <div className="sheet-name" style={{ paddingLeft: depth * 16 }}>
                {hasChildren ? (
                  <button
                    className="chevron"
                    aria-expanded={open}
                    aria-label={`${open ? "Collapse" : "Expand"} ${node.name}`}
                    onClick={(e) => {
                      e.stopPropagation();
                      onToggle(node.series);
                    }}
                  >
                    {open ? "▾" : "▸"}
                  </button>
                ) : (
                  <span className="chevron" />
                )}
                <button className="sheet-label" aria-pressed={node.series === selected} title={node.name}>
                  {node.name}
                </button>
              </div>
              <div className="sheet-bar">
                {value > 0 && (
                  <span
                    style={{
                      width: `${Math.max(0.5, (value / scale) * 100)}%`,
                      background: colors.get(node.series),
                      opacity: depth > 1 ? 0.55 : 1,
                    }}
                  />
                )}
              </div>
              <div className="num">{usd(value)}</div>
              <div className="num muted">{total ? pct(value / total) : "–"}</div>
            </div>
            {open && <Rows {...props} nodes={node.children} depth={depth + 1} />}
          </div>
        );
      })}
    </>
  );
}
