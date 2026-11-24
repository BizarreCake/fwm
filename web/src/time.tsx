import { useEffect, useMemo, useState } from "react";
import { periodLabel } from "./util";

const RANGES = [
  { label: "Since 2008", from: "2008:Q1" },
  { label: "Since 1990", from: "1990:Q1" },
  { label: "Since 1952", from: "1952:Q1" },
];

export interface TimeControls {
  periods: string[];
  start: number;
  end: number;
  period: number;
  range: string;
  playing: boolean;
  setRange: (from: string) => void;
  /** Jump to a quarter (stops playback). */
  choose: (index: number) => void;
  togglePlay: () => void;
}

/** Selected quarter, visible range and playback, shared by every chart on a page. */
export function useTimeControls(periods: string[]): TimeControls {
  const end = Math.max(0, periods.length - 1);
  const [period, setPeriod] = useState<number | null>(null);
  const [range, setRange] = useState(RANGES[0].from);
  const [playing, setPlaying] = useState(false);
  const start = useMemo(() => Math.max(0, periods.indexOf(range)), [periods, range]);
  const current = Math.min(end, Math.max(start, period ?? end));

  useEffect(() => {
    if (!playing) return;
    if (current >= end) {
      setPlaying(false);
      return;
    }
    const timer = setTimeout(() => setPeriod(current + 1), 90);
    return () => clearTimeout(timer);
  }, [playing, current, end]);

  return {
    periods,
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
        {RANGES.map((r) => (
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
        aria-label="Quarter"
        onChange={(e) => time.choose(Number(e.target.value))}
      />
      <output className="period">{periodLabel(time.periods[time.period])}</output>
    </div>
  );
}
