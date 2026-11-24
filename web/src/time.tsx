import { useEffect, useMemo, useState } from "react";
import { periodLabel } from "./util";

export interface Range {
  label: string;
  /** First period shown: a period label, or anything that sorts before the first period wanted. */
  from: string;
}

const RANGES: Range[] = [
  { label: "Since 2008", from: "2008:Q1" },
  { label: "Since 1990", from: "1990:Q1" },
  { label: "Since 1952", from: "1952:Q1" },
];

export interface TimeControls {
  periods: string[];
  ranges: Range[];
  start: number;
  end: number;
  period: number;
  range: string;
  playing: boolean;
  setRange: (from: string) => void;
  /** Jump to a quarter (stops playback). */
  choose: (index: number) => void;
  togglePlay: () => void;
  /** Jump to a quarter by label, widening the visible range if it is outside it. */
  show: (label: string) => void;
}

/** Selected quarter, visible range and playback, shared by every chart on a page. */
/** The standard ranges that fall inside the data, ending with one from its first period. */
function defaultRanges(periods: string[]): Range[] {
  const first = periods[0] ?? RANGES[RANGES.length - 1].from;
  const inside = RANGES.filter((r) => r.from > first);
  return [...inside, { label: `Since ${first.slice(0, 4)}`, from: first }];
}

export function useTimeControls(periods: string[], given?: Range[], initial = 0): TimeControls {
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const ranges = useMemo(() => given ?? defaultRanges(periods), [given, periods[0]]);
  const end = Math.max(0, periods.length - 1);
  const [period, setPeriod] = useState<number | null>(null);
  const [range, setRange] = useState(ranges[initial].from);
  const [playing, setPlaying] = useState(false);
  // Period labels sort chronologically as text, for quarters ("2008:Q1") and dates ("2008-01-02") alike.
  const startOf = (from: string) => Math.max(0, periods.findIndex((p) => p >= from));
  const start = useMemo(() => startOf(range), [periods, range]);
  const current = Math.min(end, Math.max(start, period ?? end));

  useEffect(() => {
    if (!playing) return;
    if (current >= end) {
      setPlaying(false);
      return;
    }
    const timer = setTimeout(() => setPeriod(current + 1), periods.length > 600 ? 30 : 90);
    return () => clearTimeout(timer);
  }, [playing, current, end]);

  return {
    periods,
    ranges,
    start,
    end,
    period: current,
    range,
    playing,
    setRange,
    choose: (index) => {
      setPlaying(false);
      setPeriod(index);
    },
    show: (label) => {
      const index = periods.indexOf(label);
      if (index < 0) return;
      const fits = [...ranges].sort((a, b) => startOf(b.from) - startOf(a.from)).find((r) => startOf(r.from) <= index);
      if (index < start) setRange((fits ?? ranges[ranges.length - 1]).from);
      setPlaying(false);
      setPeriod(index);
    },
    togglePlay: () => {
      if (!playing && current >= end) setPeriod(start);
      setPlaying(!playing);
    },
  };
}

export function TimeBar({ time }: { time: TimeControls }) {
  return (
    <div className="filters">
      <div className="segmented" role="group" aria-label="Time range">
        {time.ranges.map((r) => (
          <button key={r.from} aria-pressed={time.range === r.from} onClick={() => time.setRange(r.from)}>
            {r.label}
          </button>
        ))}
      </div>
      <button className="play" onClick={time.togglePlay}>
        {time.playing ? "❚❚ Pause" : "▶ Play"}
      </button>
      <input
        className="slider"
        type="range"
        min={time.start}
        max={time.end}
        value={time.period}
        aria-label="Period"
        onChange={(e) => time.choose(Number(e.target.value))}
      />
      <output className="period">{periodLabel(time.periods[time.period])}</output>
    </div>
  );
}
