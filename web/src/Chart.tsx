import { useState, type ReactNode } from "react";
import { useContextData } from "./context";
import { periodLabel, useWidth, yearTicks } from "./util";

export interface Frame {
  x: (index: number) => number;
  y: (value: number) => number;
  plotWidth: number;
  plotHeight: number;
  step: number;
}

export interface TooltipRow {
  key: string;
  label: string;
  value: string;
  color?: string;
}

interface Props {
  periods: string[];
  start: number;
  end: number;
  domain: [number, number];
  yTicks: number[];
  formatY: (value: number) => string;
  height: number;
  period: number;
  onPeriod: (index: number) => void;
  tooltip: (index: number) => TooltipRow[];
  ariaLabel: string;
  /** Inset the x scale by half a step so bars centred on a period fit inside the plot. */
  banded?: boolean;
  children: (frame: Frame) => ReactNode;
}

const MARGIN = { top: 14, right: 12, bottom: 22, left: 48 };

/** Shared time-series frame: axes, selected-period marker, crosshair, tooltip, click/drag to set period. */
export function Chart(props: Props) {
  const { periods, start, end, domain, yTicks, formatY, height, period, onPeriod, tooltip, ariaLabel, banded, children } = props;
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const [dragging, setDragging] = useState(false);

  const plotWidth = Math.max(10, width - MARGIN.left - MARGIN.right);
  const plotHeight = height - MARGIN.top - MARGIN.bottom;
  const count = end - start;
  const step = banded ? plotWidth / (count + 1) : plotWidth / Math.max(1, count);
  const inset = banded ? step / 2 : 0;
  const x = (i: number) => MARGIN.left + inset + (i - start) * step;
  const y = (v: number) => MARGIN.top + plotHeight * (1 - (v - domain[0]) / (domain[1] - domain[0] || 1));
  const frame: Frame = { x, y, plotWidth, plotHeight, step };

  const indexAt = (clientX: number, element: Element) => {
    const local = clientX - element.getBoundingClientRect().left;
    const i = Math.round((local - MARGIN.left - inset) / step) + start;
    return Math.min(end, Math.max(start, i));
  };

  // Quarters with a policy announcement, when the context data covers the same quarters as this chart.
  const context = useContextData();
  const events = context && context.periods.length === periods.length ? context.events : [];
  const eventQuarters = [...new Set(events.map((e) => e.index))].filter((i) => i >= start && i <= end);
  const hoverEvents = hover === null ? [] : events.filter((e) => e.index === hover);

  const rows = hover === null ? [] : tooltip(hover);
  const tipLeft = hover === null ? 0 : x(hover);
  const flip = tipLeft > width * 0.6;

  return (
    <div ref={ref} className="chart" style={{ height }}>
      {width > 0 && (
        <svg
          width={width}
          height={height}
          role="img"
          aria-label={ariaLabel}
          onPointerMove={(e) => {
            const i = indexAt(e.clientX, e.currentTarget);
            setHover(i);
            if (dragging) onPeriod(i);
          }}
          onPointerDown={(e) => {
            e.currentTarget.setPointerCapture(e.pointerId);
            setDragging(true);
            onPeriod(indexAt(e.clientX, e.currentTarget));
          }}
          onPointerUp={() => setDragging(false)}
          onPointerLeave={() => {
            setHover(null);
            setDragging(false);
          }}
        >
          {yTicks.map((tick) => (
            <g key={tick}>
              <line x1={MARGIN.left} x2={width - MARGIN.right} y1={y(tick)} y2={y(tick)} className={tick === 0 ? "axis" : "grid"} />
              <text x={MARGIN.left - 6} y={y(tick)} textAnchor="end" dominantBaseline="central" className="tick">
                {formatY(tick)}
              </text>
            </g>
          ))}
          {yearTicks(periods, start, end, plotWidth).map((i) => (
            <text key={i} x={x(i)} y={height - 6} textAnchor="middle" className="tick">
              {periods[i].slice(0, 4)}
            </text>
          ))}
          {eventQuarters.map((i) => (
            <path key={`event${i}`} d={`M${x(i) - 3.5},3 L${x(i) + 3.5},3 L${x(i)},10 Z`} className="event-mark" />
          ))}
          {children(frame)}
          {period >= start && period <= end && (
            <line x1={x(period)} x2={x(period)} y1={MARGIN.top} y2={MARGIN.top + plotHeight} className="marker" />
          )}
          {hover !== null && hover !== period && (
            <line x1={x(hover)} x2={x(hover)} y1={MARGIN.top} y2={MARGIN.top + plotHeight} className="crosshair" />
          )}
        </svg>
      )}
      {hover !== null && rows.length > 0 && (
        <div className="tooltip" style={flip ? { right: width - tipLeft + 12 } : { left: tipLeft + 12 }}>
          <div className="tooltip-title">{periodLabel(periods[hover])}</div>
          {rows.map((row) => (
            <div key={row.key} className="tooltip-row">
              {row.color && <span className="key" style={{ background: row.color }} />}
              <span className="tooltip-value">{row.value}</span>
              <span className="tooltip-label">{row.label}</span>
            </div>
          ))}
          {hoverEvents.map((event) => (
            <div key={event.date + event.title} className="tooltip-event">
              ▾ {event.date.slice(5)}: {event.title}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
