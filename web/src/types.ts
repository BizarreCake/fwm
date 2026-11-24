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
