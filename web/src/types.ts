export interface Measures {
  level: (number | null)[];
  transactions: (number | null)[];
  other_change: (number | null)[];
}

/** One sector's position in an instrument, as holder (asset) or issuer (liability). */
export interface Position extends Measures {
  code: string;
  name: string;
  detail: string;
  group: string;
  sector_id: string | null;
  series: string;
  basis: "market" | "book";
  /** Set when this row is a part of another row in the same group, and so is not added to the group's total. */
  part_of?: string;
}

export interface Group extends Measures {
  id: string;
  name: string;
  sectors: Position[];
}

export interface SideView extends Measures {
  series: string;
  excludes_discrepancy: boolean;
  groups: Group[];
}

export interface InstrumentView {
  id: string;
  name: string;
  unit: string;
  periods: string[];
  group_order: string[];
  holders: SideView;
  issuers: SideView | null;
  discrepancy: { series: string; level: (number | null)[] } | null;
  source: { name: string; url: string; table: string; published_at: string | null; latest_period: string };
  notes: { sides: string; other_change: string; coverage: string; issuers: string | null };
}

export interface InstrumentSummary {
  id: string;
  name: string;
  holders_total: number | null;
  has_issuers: boolean;
}

export type SideName = "holders" | "issuers";

export type Mode = "usd" | "share" | "gdp";

export interface SheetNode {
  series: string;
  name: string;
  basis: "market" | "book";
  /** Z.1 instrument table this line also appears in, e.g. "F3_2" for Treasury securities. */
  instrument: string | null;
  level: (number | null)[];
  transactions: (number | null)[];
  other_change: (number | null)[];
  children: SheetNode[];
  memos: SheetNode[];
}

export interface SectorView {
  id: string;
  name: string;
  unit: string;
  periods: string[];
  assets: SheetNode;
  liabilities: SheetNode | null;
  source: { name: string; url: string; table: string; published_at: string | null; latest_period: string };
  notes: { structure: string; liabilities: string | null; other_change: string };
}

export interface SectorSummary {
  id: string;
  name: string;
  sector_code: string;
  total_assets: number | null;
  total_liabilities: number | null;
  /** Set when this sector is a part of another listed sector. */
  part_of?: string | null;
}

export interface Move {
  instrument_id: string;
  instrument: string;
  side: SideName;
  sector: string;
  sector_id: string | null;
  group: string;
  series: string;
  level: number | null;
  amount: number;
  score: number | null;
  /** Last quarter with a move at least this large in the same direction; null = never, since 1952. */
  largest_since: string | null;
  history_from: string;
  history: (number | null)[];
}

export interface Overview {
  period: string;
  min_flow: number;
  window_quarters: number;
  unusual_flows: Move[];
  largest_flows: Move[];
  valuation_changes: Move[];
  instruments: { id: string; name: string; composite: boolean; held: number | null; transactions: number | null; other_change: number | null }[];
  sectors: SectorSummary[];
  notes: { unusual: string; coverage: string; valuation: string };
}

export interface Family {
  id: string;
  name: string;
  instrument_id: string;
  debt_like: boolean;
  tables: string[];
  /** Amount per sector group id, per quarter. */
  issuers: Record<string, number[]>;
  holders: Record<string, number[]>;
}

export interface SystemMapView {
  periods: string[];
  unit: string;
  groups: { id: string; name: string }[];
  families: Family[];
  notes: { reading: string; sides: string; coverage: string };
}

export interface PolicyEvent {
  date: string;
  period: string;
  /** Index of the quarter in `periods`. */
  index: number;
  kind: string;
  title: string;
  detail: string;
  url: string;
}

export interface RateSeries {
  id: string;
  name: string;
  short_name: string;
  /** Quarterly averages, percent per year. */
  values: (number | null)[];
  latest: { date: string; value: number };
}

export interface ContextView {
  periods: string[];
  rates: RateSeries[];
  /** Nominal GDP over the four quarters ending in each quarter, USD millions. */
  gdp: { series: string; values: (number | null)[] };
  events: PolicyEvent[];
  notes: { rates: string; gdp: string; events: string };
}

export interface WeeklyLine {
  id: string;
  name: string;
  /** H.4.1 series behind the line; empty for the computed "other" line. */
  series: string[];
  computed: boolean;
  level: number[];
  children: WeeklyLine[];
}

export interface WeeklyView {
  id: string;
  name: string;
  /** Dates, one per week. */
  periods: string[];
  assets: { total: number[]; lines: WeeklyLine[] };
  liabilities: { total: number[]; lines: WeeklyLine[] };
  /** The latest quarter in the quarterly accounts, and the last week inside it. */
  quarterly: { period: string; index: number; sector_id: string };
  events: PolicyEvent[];
  source: { name: string; url: string; published_at: string | null; latest: string };
  notes: { basis: string; other: string; counterparties: string };
}

export interface ForeignHolder {
  id: string;
  name: string;
  region?: string;
  total: (number | null)[];
  total_net: (number | null)[];
  long_term: (number | null)[];
  long_term_net: (number | null)[];
  long_term_valuation: (number | null)[];
  /** Derived: change in bonds and notes not explained by purchases and valuation. */
  long_term_other: (number | null)[];
  short_term: (number | null)[];
  short_term_net: (number | null)[];
}

export interface ForeignRegion extends ForeignHolder {
  region: string;
  /** Held in the region by countries not published separately. */
  unlisted: (number | null)[];
  countries: string[];
}

export interface ForeignView {
  id: string;
  name: string;
  assets: { id: string; name: string }[];
  has_bills: boolean;
  /** Months, as YYYY-MM. */
  periods: string[];
  total: ForeignHolder;
  official: ForeignHolder;
  private: ForeignHolder;
  regions: ForeignRegion[];
  countries: ForeignHolder[];
  memo: ForeignHolder[];
  quarterly: { instrument_id: string; instrument_name: string; sector_id: string; latest: string; note: string; level: (number | null)[] } | null;
  source: { name: string; url: string; file: string; latest: string };
  notes: { custody: string; scope: string; valuation: string; history: string; other: string; missing: string; unallocated?: string };
}

export interface CountrySummary {
  id: string;
  name: string;
  kind: "country" | "group";
  region: string | null;
  /** US securities held there, latest month. */
  holds_us: number | null;
  /** Its securities held by US residents, latest month. */
  held_by_us: number | null;
}

export interface CountryLine {
  id: string;
  name: string;
  scope: string;
  page: string | null;
  total: (number | null)[];
  total_net: (number | null)[];
  long_term_valuation: (number | null)[];
  all_countries: (number | null)[];
  rank: number | null;
  ranked_among: number;
}

export interface CountrySide {
  lines: CountryLine[];
  total: (number | null)[];
  total_net: (number | null)[];
  long_term_valuation: (number | null)[];
}

export interface CountryView {
  id: string;
  name: string;
  kind: "country" | "group";
  region: string | null;
  periods: string[];
  holds_us: CountrySide;
  held_by_us: CountrySide;
  source: { name: string; url: string; latest: string };
  notes: { scope: string; custody: string; outward: string; coverage: string; history: string };
}
