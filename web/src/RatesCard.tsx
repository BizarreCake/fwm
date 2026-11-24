import { Chart } from "./Chart";
import { useContextData } from "./context";
import type { TimeControls } from "./time";
import { periodLabel, ticks } from "./util";

const SHOWN = ["fed_funds", "treasury_2y", "treasury_10y"];
const COLORS: Record<string, string> = { fed_funds: "var(--s1)", treasury_2y: "var(--s2)", treasury_10y: "var(--s3)" };
const rate = (value: number) => `${value.toFixed(2)}%`;

/** Interest rates on the page's time axis, with the policy events of the selected quarter. */
export function RatesCard({ time }: { time: TimeControls }) {
  const context = useContextData();
  if (!context || context.rates.length === 0 || context.periods.length !== time.periods.length) return null;
  const { periods, start, end, period } = time;
  const series = SHOWN.map((id) => context.rates.find((r) => r.id === id)).filter((r) => r !== undefined);

  let max = 1;
  for (const s of series) for (let i = start; i <= end; i++) max = Math.max(max, s.values[i] ?? 0);
  const yTicks = ticks(0, max, 4);
  const top = Math.max(max, yTicks[yTicks.length - 1]);

  const here = context.events.filter((e) => e.index === period);
  const before = context.events.filter((e) => e.index < period);
  const previous = here.length === 0 && before.length ? before[before.length - 1] : null;

  return (
    <section className="card">
      <div className="card-head">
        <h2>Interest rates and Fed announcements</h2>
        <span className="legend">
          {series.map((s) => (
            <span key={s.id} className="legend-item">
              <span className="swatch" style={{ background: COLORS[s.id] }} /> {s.name}
            </span>
          ))}
        </span>
      </div>
      <Chart
        periods={periods}
        start={start}
        end={end}
        domain={[0, top]}
        yTicks={yTicks}
        formatY={(v) => `${v}%`}
        height={180}
        period={period}
        onPeriod={time.choose}
        ariaLabel="Interest rates over time, quarterly averages"
        tooltip={(i) =>
          series.filter((s) => s.values[i] !== null).map((s) => ({ key: s.id, label: s.short_name, value: rate(s.values[i]!), color: COLORS[s.id] }))
        }
      >
        {({ x, y }) =>
          series.map((s) => {
            let d = "";
            let pen = false;
            for (let i = start; i <= end; i++) {
              const v = s.values[i];
              if (v === null) {
                pen = false;
                continue;
              }
              d += `${pen ? "L" : "M"}${x(i)},${y(v)} `;
              pen = true;
            }
            const now = s.values[period];
            return (
              <g key={s.id}>
                <path d={d} fill="none" stroke={COLORS[s.id]} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
                {now !== null && <circle cx={x(period)} cy={y(now)} r={4} fill={COLORS[s.id]} stroke="var(--surface)" strokeWidth={2} />}
              </g>
            );
          })
        }
      </Chart>
      <div className="events">
        {here.map((event) => (
          <p key={event.date + event.title}>
            <span className="event-date">{event.date}</span> <strong>{event.title}.</strong> {event.detail}{" "}
            <a href={event.url}>Press release</a>
          </p>
        ))}
        {previous && (
          <p className="muted">
            No announcement on the calendar in {periodLabel(periods[period])}. Most recent before it:{" "}
            <span className="event-date">{previous.date}</span> {previous.title}. <a href={previous.url}>Press release</a>
          </p>
        )}
        {here.length === 0 && !previous && <p className="muted">The calendar of Fed announcements starts in {context.events[0]?.date.slice(0, 4)}.</p>}
      </div>
      <p className="muted small">
        {context.notes.rates} ▾ marks on the charts are quarters with a Fed announcement. {context.notes.events}
      </p>
    </section>
  );
}
