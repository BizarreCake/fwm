export interface Measures {
  level: number[];
  transactions: number[];
  other_change: (number | null)[];
}

export interface Sector extends Measures {
  sector_id: string | null;
  code: string;
  name: string;
  basis: "market" | "book";
  level_series: string;
  transactions_series: string;
}

export interface Group extends Measures {
  id: string;
  name: string;
  note: string;
  sectors: Sector[];
}

export interface Total extends Measures {
  series: string;
}

export interface HoldersView {
  instrument: string;
  unit: string;
  periods: string[];
  period_ends: string[];
  groups: Group[];
  totals: {
    liability_face: Total;
    bills_face: Total;
    holders_market: Total;
    valuation_gap: Total;
    nonmarketable_face: { series: string; level: (number | null)[] };
  };
  source: {
    name: string;
    url: string;
    table: string;
    published_at: string | null;
    ingested_at: string;
    latest_period: string;
  };
  notes: { valuation: string; other_change: string; coverage: string };
}

export type Mode = "usd" | "share";

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
}
