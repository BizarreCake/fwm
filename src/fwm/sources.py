"""The registry of data sources: what is loaded, where it lives, and how to refresh it.

Everything that knows the list of sources reads it from here: `fwm ingest`, `fwm status`,
and docs/sources.md, which is written from this file by `fwm sources --write`.

A Source is one thing that is downloaded and loaded together. It records one or more
Releases in the `source_release` table, each with the latest period it holds; the
frequency and usual publication lag of a release are what `fwm status` uses to say
whether newer data has probably been published.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from fwm.paths import DB_PATH, DOC_PATH, RAW, ROOT  # noqa: F401  (ROOT and DOC_PATH are read through this module)


@dataclass(frozen=True)
class Release:
    id: str            # source_release.source_id
    what: str
    frequency: str     # quarter, half-year, month, week or day
    lag_days: int      # usual days from the end of a period to its publication; approximate
    published_at: str  # what source_release.published_at holds: "release" time or "download" time


@dataclass(frozen=True)
class Source:
    id: str
    group: str                       # the name `fwm ingest --only` takes; a group refreshes together
    name: str
    publisher: str
    url: str
    covers: str
    raw_dir: str                     # under data/raw
    releases: tuple[Release, ...]
    tables: dict[str, str]           # tables this source alone fills -> "columns: what a row is"
    shares: tuple[str, ...] = ()     # tables in SHARED_TABLES it fills its own rows of
    takes: str | None = None         # how long a refresh takes
    vintages: str | None = None      # how past downloads are kept, if they are
    rebuilds: tuple[str, ...] = ()   # keys in `computed` rebuilt after loading
    needs: tuple[str, ...] = ()      # other sources read together with this one
    notes: tuple[str, ...] = field(default=())

    @property
    def module(self) -> str:
        """The loader: src/fwm/loaders/<id with underscores>.py, with download(raw_dir) and ingest(raw_dir, db_path)."""
        return f"fwm.loaders.{self.id.replace('-', '_')}"


SOURCES: tuple[Source, ...] = (
    Source(
        id="z1", group="z1", name="Federal Reserve Z.1, Financial Accounts of the United States",
        publisher="Federal Reserve Board", url="https://www.federalreserve.gov/releases/z1/",
        covers="US sector balance sheets and instruments, quarterly from 1952:Q1, in US dollars. Also US nominal GDP.",
        raw_dir="z1",
        releases=(Release("fed_z1", "US financial accounts", "quarter", 75, "release"),),
        tables={
            "z1_series": "series_id, description, unit, table_id, table_name, line: one row per series in each table it appears in",
            "z1_observations": "series_id, period, period_end, value: one value per series and quarter, USD millions",
            "z1_structure": "table_id, series_id, position, parent_series_id, role: the line hierarchy of each table",
        },
        vintages="Each release is kept as data/raw/z1/vintages/z1_<publication date>.zip.",
        rebuilds=("overview", "system_map"),
        notes=("Series ids carry a measure prefix: FL levels, FU transactions, FR revaluations, FV other changes.",),
    ),
    Source(
        id="rates", group="rates", name="Federal Reserve H.15, Selected Interest Rates",
        publisher="Federal Reserve Board", url="https://www.federalreserve.gov/releases/h15/",
        covers="Daily fed funds rate and 3-month, 2-year and 10-year Treasury yields.",
        raw_dir="h15", takes="seconds",
        releases=(Release("fed_h15", "US interest rates", "day", 3, "release"),),
        tables={}, shares=("rate_series", "rates_daily"),
        notes=("Its rows are economy `us`.",),
    ),
    Source(
        id="fed-weekly", group="fed-weekly", name="Federal Reserve H.4.1, Factors Affecting Reserve Balances",
        publisher="Federal Reserve Board", url="https://www.federalreserve.gov/releases/h41/",
        covers="The Fed's balance sheet every Wednesday from December 2002, in US dollars.",
        raw_dir="h41", takes="seconds",
        releases=(Release("fed_h41", "Weekly Fed balance sheet", "week", 2, "release"),),
        tables={
            "weekly_series": "series_id, source, description: the H.4.1 series loaded",
            "weekly_observations": "series_id, date, value: Wednesday levels, USD millions",
        },
    ),
    Source(
        id="tic", group="tic", name="US Treasury TIC, SLT Tables 1, 2 and 3",
        publisher="US Department of the Treasury", url="https://home.treasury.gov/data/treasury-international-capital-tic-system",
        covers="Foreign holdings of US securities and US holdings of foreign securities, by country, monthly from January 2020.",
        raw_dir="tic", takes="seconds",
        releases=(
            Release("treasury_tic_slt1", "US long-term securities held by foreigners", "month", 50, "download"),
            Release("treasury_tic_slt2", "Foreign long-term securities held by US residents", "month", 50, "download"),
            Release("treasury_tic_slt3", "Treasury securities held by foreigners", "month", 50, "download"),
        ),
        tables={
            "tic_country": "source, code, name, kind, region, position: the countries and groups in each table, with the Treasury's own codes",
            "tic_holdings": "asset, code, month, total, total_net, long_term, long_term_net, long_term_valuation, short_term, "
                            "short_term_net: holdings and monthly net purchases, USD millions",
        },
        vintages="Each month's files are kept as data/raw/tic/vintages/slt_table<n>_<month>.txt.",
        needs=("links",),
        notes=("Country pages are keyed by the Treasury's country names; src/fwm/curated/country_codes.csv ties them to ISO codes.",),
    ),
    Source(
        id="ecb-weekly", group="ecb", name="ECB, Weekly financial statement of the Eurosystem (ILM)",
        publisher="European Central Bank", url="https://data.ecb.europa.eu/data/datasets/ILM",
        covers="The Eurosystem's balance sheet every Friday from January 1999, in euro.",
        raw_dir="ecb/weekly", takes="under a minute for the whole ecb group",
        releases=(Release("ecb_weekly", "Weekly Eurosystem balance sheet", "week", 5, "download"),),
        tables={"eurosystem_weekly": "series_id, date, value: Friday levels, EUR millions"},
    ),
    Source(
        id="ecb-context", group="ecb", name="ECB key interest rate, yield curve, GDP and dollar exchange rate",
        publisher="European Central Bank", url="https://data.ecb.europa.eu/",
        covers="Deposit facility rate and AAA government yields (daily), euro-area nominal GDP (quarterly), US dollars per euro (daily).",
        raw_dir="ecb/context",
        releases=(
            Release("ecb_rates", "Euro-area interest rates", "day", 3, "download"),
            Release("ecb_gdp", "Euro-area GDP", "quarter", 70, "download"),
            Release("ecb_fx", "US dollars per euro", "day", 3, "download"),
        ),
        tables={}, shares=("rate_series", "rates_daily", "gdp_quarterly", "fx_daily"),
        notes=("Its rows are economy `ea` and exchange-rate pair `USD/EUR` (US dollars per euro), the only dollar rate in the "
               "database. GDP is not seasonally adjusted.",),
    ),
    Source(
        id="ecb-accounts", group="ecb", name="ECB, Quarterly Sector Accounts for the euro area (QSA)",
        publisher="European Central Bank", url="https://data.ecb.europa.eu/data/datasets/QSA",
        covers="Euro-area sector balance sheets, instruments and who-holds-whose detail, quarterly from 1999:Q1, in euro.",
        raw_dir="ecb",
        releases=(Release("ecb_qsa", "Euro-area financial accounts", "quarter", 120, "download"),),
        tables={
            "qsa_series": "key, counterpart_area, sector, counterpart_sector, side, measure, instrument, maturity: the ECB series "
                          "key split into its dimensions",
            "qsa_observations": "key, period, value: one value per series and quarter, EUR millions",
        },
        vintages="Each download is kept as data/raw/ecb/vintages/qsa_I10_<latest quarter>_<download date>.csv.gz.",
        rebuilds=("overview:ea", "system_map:ea"),
        needs=("ecb-context",),
    ),
    Source(
        id="jp-context", group="boj", name="Japan: policy rate, government bond yields, GDP and yen exchange rate",
        publisher="BIS, Ministry of Finance of Japan, OECD, ECB",
        url="https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/index.htm",
        covers="Bank of Japan policy rate (BIS, daily), 2- and 10-year government bond yields (Ministry of Finance, daily), "
               "nominal GDP (OECD, quarterly), yen per euro (ECB, daily).",
        raw_dir="boj/context", takes="under a minute for the whole boj group",
        releases=(
            Release("jp_policy_rate", "Bank of Japan policy rate (BIS)", "day", 10, "download"),
            Release("jp_yields", "Japanese government bond yields (Ministry of Finance)", "day", 3, "download"),
            Release("jp_gdp", "Japanese GDP (OECD)", "quarter", 50, "download"),
            Release("jp_fx", "Yen per euro (ECB)", "day", 3, "download"),
        ),
        tables={}, shares=("rate_series", "rates_daily", "gdp_quarterly", "fx_daily"),
        needs=("ecb-context",),
        notes=("Its rows are economy `jp` and exchange-rate pair `JPY/EUR` (yen per euro). GDP is seasonally adjusted.",
               "Dollars per yen is the `USD/EUR` rate divided by the `JPY/EUR` rate for the same day, so it needs the ecb group loaded.",),
    ),
    Source(
        id="boj-accounts", group="boj", name="Bank of Japan, Flow of Funds Accounts",
        publisher="Bank of Japan", url="https://www.boj.or.jp/en/statistics/sj/index.htm",
        covers="Japan's sector balance sheets and instruments, quarterly from 1997:Q4, in yen.",
        raw_dir="boj",
        releases=(Release("boj_fof", "Japan's financial accounts", "quarter", 80, "release"),),
        tables={"jff_observations": "series_id, period, value: one value per series and quarter, JPY millions"},
        vintages="Each file is kept as data/raw/boj/vintages/fof-<date the Bank prepared it>.zip.",
        rebuilds=("overview:jp", "system_map:jp"),
        needs=("jp-context",),
        notes=("Series ids are FOF_FFA + S, F or R (stock, flow, reconciliation) + sector + A or L + item.",),
    ),
    Source(
        id="links", group="links", name="IMF portfolio investment positions and BIS locational banking statistics",
        publisher="International Monetary Fund, Bank for International Settlements", url="https://data.imf.org/en/datasets/IMF.STA:PIP",
        covers="Positions between pairs of countries in US dollars: holdings of equity and of debt securities (IMF, end of "
               "June and December from 2001), and bank claims and liabilities (BIS, quarterly from 1999).",
        raw_dir="links", takes="about four minutes",
        releases=(
            Release("imf_pip", "Portfolio holdings by country pair (IMF)", "half-year", 300, "download"),
            Release("bis_lbs", "Bank positions by country pair (BIS)", "quarter", 120, "download"),
        ),
        tables={"xb_positions": "kind, denom, period, reporter, counterpart, value: one position of a reporting country towards a "
                                "counterpart, USD millions"},
        rebuilds=("links",),
        notes=(
            "reporter is an ISO two-letter code (or 5A, all BIS reporting countries); counterpart keeps the source's own code: "
            "three letters in IMF rows, two in BIS rows. src/fwm/curated/country_codes.csv maps between them.",
            "Past downloads are not kept: each refresh replaces the four files.",
        ),
    ),
)

# Tables that belong to no single source. The first four hold every economy's rates, GDP and exchange rates:
# each loader replaces its own economy's rows (src/fwm/economies/base.py). US GDP is not in them; it is a Z.1 series.
SHARED_TABLES = {
    "rate_series": "economy, series_id, name, short_name, source_series, shown: the interest rates loaded for each economy",
    "rates_daily": "economy, series_id, date, value: percent per year",
    "gdp_quarterly": "economy, period, value: nominal GDP per quarter, millions of the economy's currency",
    "fx_daily": "pair, date, value: ECB reference rates, units of the first currency per euro",
    "source_release": "source_id, name, url, published_at, ingested_at, latest_period: one row per release above, written at each load",
    "computed": "key, value: results worked out once at load time and stored as JSON",
}
COMPUTED = {
    "overview": "The US overview page: unusual and largest flows of the latest quarter.",
    "system_map": "The US system map: what each sector group holds of each instrument family, every quarter.",
    "overview:ea": "The same overview for the euro area.",
    "system_map:ea": "The same map for the euro area.",
    "overview:jp": "The same overview for Japan.",
    "system_map:jp": "The same map for Japan.",
    "links": "The tables of positions between the six large economies.",
}
# Files in the repository that are maintained by hand, not downloaded.
CURATED = {
    "src/fwm/curated/events.csv": "Federal Reserve announcements shown on US charts. Add a row with the date, kind, title, detail and press release.",
    "src/fwm/curated/events_ea.csv": "ECB announcements, the same way.",
    "src/fwm/curated/events_jp.csv": "Bank of Japan announcements, the same way. Titles follow the Bank's own release titles.",
    "src/fwm/curated/country_codes.csv": "ISO two- and three-letter codes, names and other names for 249 countries. Built once from the IMF "
                                 "and BIS code lists by scripts/make_country_codes.py and corrected by hand; edit it directly.",
}
GROUPS = tuple(dict.fromkeys(source.group for source in SOURCES))


def by_id(source_id: str) -> Source:
    return next(source for source in SOURCES if source.id == source_id)


def selected(only: str | None) -> list[Source]:
    """The sources a refresh covers: all, one group, or one source."""
    if only is None:
        return list(SOURCES)
    chosen = [source for source in SOURCES if only in (source.group, source.id)]
    if not chosen:
        raise ValueError(f"No source {only!r}; choose from {', '.join(names())}")
    return chosen


def names() -> list[str]:
    return list(dict.fromkeys([*GROUPS, *(source.id for source in SOURCES)]))


# Loading

DESCRIBE: dict[str, Callable[[dict], str]] = {
    "z1": lambda s: f"Loaded {s['observations']:,} observations across {s['series']:,} series; latest quarter {s['latest_period']}",
    "rates": lambda s: f"Loaded {s['observations']:,} daily interest rates; latest {s['latest']}",
    "fed-weekly": lambda s: f"Loaded {s['observations']:,} weekly Fed balance sheet values; latest {s['latest']}",
    "tic": lambda s: f"Loaded foreign holdings of US securities for {s['countries']} countries; latest {s['latest']}",
    "ecb-weekly": lambda s: f"Loaded {s['weeks']:,} weeks of the Eurosystem's balance sheet; latest {s['latest']}",
    "ecb-context": lambda s: f"Loaded euro-area rates to {s['rates_latest']}, GDP to {s['gdp_latest']}, dollar exchange rate to {s['fx_latest']}",
    "ecb-accounts": lambda s: f"Loaded {s['observations']:,} euro-area observations in {s['series']:,} series; latest {s['latest']}",
    "jp-context": lambda s: f"Loaded Japanese rates to {s['rates_latest']}, GDP to {s['gdp_latest']}, yen exchange rate to {s['fx_latest']}",
    "boj-accounts": lambda s: f"Loaded {s['observations']:,} Japanese observations in {s['series']:,} series; latest {s['latest']}",
    "links": lambda s: f"Loaded {s['observations']:,} positions between countries; latest {s['latest']}",
}


def rebuild(con, key: str) -> None:
    """Work out one stored result again and save it in `computed`."""
    from fwm.views import links, overview, systemmap

    name, _, economy = key.partition(":")
    if name == "links":
        links.build(con)
    else:
        {"overview": overview, "system_map": systemmap}[name].build(con, economy or "us")


def load(source: Source, download: bool = True, db_path: Path = DB_PATH) -> str:
    """Download (unless told not to) and load one source, then rebuild what is stored from it; returns what was loaded."""
    import importlib

    import duckdb

    module = importlib.import_module(source.module)
    raw = RAW / source.raw_dir
    if download:
        module.download(raw)
    summary = module.ingest(raw, db_path)
    if source.rebuilds:
        con = duckdb.connect(str(db_path))
        try:
            for key in source.rebuilds:
                rebuild(con, key)
        finally:
            con.close()
    return DESCRIBE[source.id](summary)


# Freshness

def period_end(period: str) -> dt.date:
    """The last day a period label covers: 2026:Q2, 2026-09 or 2026-11-20."""
    if ":Q" in period:
        year, quarter = int(period[:4]), int(period[-1])
        return dt.date(year + (quarter == 4), quarter * 3 % 12 + 1, 1) - dt.timedelta(days=1)
    if len(period) == 7:
        year, month = int(period[:4]), int(period[5:])
        return dt.date(year + (month == 12), month % 12 + 1, 1) - dt.timedelta(days=1)
    return dt.date.fromisoformat(period)


def next_period_end(period: str, frequency: str) -> dt.date:
    end = period_end(period)
    if frequency == "day":
        return end + dt.timedelta(days=1)
    if frequency == "week":
        return end + dt.timedelta(days=7)
    months = {"month": 1, "quarter": 3, "half-year": 6}[frequency]
    first = (end + dt.timedelta(days=1)).replace(day=1)
    month = first.month - 1 + months
    return dt.date(first.year + month // 12, month % 12 + 1, 1) - dt.timedelta(days=1)


def status(con, today: dt.date | None = None) -> list[dict]:
    """One row per release: what is loaded, when the next period is usually published, and whether that has passed."""
    today = today or dt.date.today()
    has_table = con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name = 'source_release'").fetchone()[0]
    loaded = {row[0]: row[1:] for row in con.execute(
        "SELECT source_id, latest_period, ingested_at, published_at FROM source_release").fetchall()} if has_table else {}
    rows = []
    for source in SOURCES:
        for release in source.releases:
            row = {"source": source.id, "group": source.group, "release": release.id, "what": release.what, "frequency": release.frequency,
                   "refresh": f"uv run fwm ingest --only {source.group}"}
            if release.id not in loaded:
                rows.append({**row, "latest": None, "loaded_on": None, "next_due": None, "state": "not loaded"})
                continue
            latest, ingested_at, _ = loaded[release.id]
            due = next_period_end(latest, release.frequency) + dt.timedelta(days=release.lag_days)
            loaded_on = ingested_at.date()
            # Stale when the next period is due and no load has been tried since: since the due date for slow
            # releases, within the last day or week for daily and weekly ones.
            tried = {"day": today, "week": today - dt.timedelta(days=6)}.get(release.frequency, due)
            rows.append({**row, "latest": latest, "loaded_on": loaded_on.isoformat(), "next_due": due.isoformat(),
                         "state": "newer data probably published" if due <= today and loaded_on < tried else "current"})
    return rows


def unregistered(con) -> list[str]:
    """Release rows in the database that no source here claims: left over from an older layout."""
    known = {release.id for source in SOURCES for release in source.releases}
    return [row[0] for row in con.execute("SELECT source_id FROM source_release").fetchall() if row[0] not in known]


# Documentation

def render() -> str:
    """docs/sources.md, written from the registry."""
    out = [
        "# Data sources and database",
        "",
        "Written from `src/fwm/sources.py` by `uv run fwm sources --write`. Edit the registry, not this file.",
        "For what each source can and cannot say, and what is wanted next, see `docs/data.md`.",
        "",
        "## Keeping the data fresh",
        "",
        "- `uv run fwm status` lists every release: the latest period loaded, when it was loaded, when the next period is "
        "usually published, and whether that date has passed.",
        "- `uv run fwm ingest` downloads and loads everything. `uv run fwm ingest --only <name>` refreshes one group "
        f"({', '.join(GROUPS)}) or one source by its id below.",
        "- `--no-download` reloads from the files already in `data/raw`, which is what to use after changing a loader.",
        "- Every load replaces that source's tables in full, so a refresh also picks up revisions to past periods.",
        "- The publication lags below are approximate; they only drive the hint in `fwm status`.",
        "",
        "| Source id | Refresh with | Release | Frequency | Usual lag |",
        "| --- | --- | --- | --- | --- |",
    ]
    for source in SOURCES:
        for release in source.releases:
            out.append(f"| `{source.id}` | `--only {source.group}` | {release.what} | {release.frequency} | {release.lag_days} days |")
    out += ["", "## Sources", ""]
    for source in SOURCES:
        out += [f"### {source.name} (`{source.id}`)", "",
                f"- **Publisher:** {source.publisher}. <{source.url}>",
                f"- **Covers:** {source.covers}",
                f"- **Refresh:** `uv run fwm ingest --only {source.group}`" + (f" ({source.takes})" if source.takes else "")
                + (f", or `--only {source.id}` for this source alone." if source.group != source.id else "."),
                f"- **Loader:** `src/{source.module.replace('.', '/')}.py`; downloads go to `data/raw/{source.raw_dir}/`.",
                "- **Releases recorded:** " + "; ".join(
                    f"`{r.id}` ({r.frequency}; `published_at` is the {r.published_at} time)" for r in source.releases) + ".",
                "- **Past downloads:** " + (source.vintages or "not kept; each refresh replaces the files.")]
        if source.rebuilds:
            out.append("- **Rebuilds:** " + ", ".join(f"`{key}`" for key in source.rebuilds) + " in `computed`.")
        if source.needs:
            out.append("- **Read together with:** " + ", ".join(f"`{name}`" for name in source.needs) + ".")
        if source.tables:
            out.append("- **Tables:**")
            out += [f"  - `{table}` — {text}" for table, text in source.tables.items()]
        if source.shares:
            out.append("- **Fills its rows of the shared tables:** " + ", ".join(f"`{table}`" for table in source.shares) + ".")
        out += [f"- {note}" for note in source.notes]
        out.append("")
    out += ["## Tables that belong to no single source", ""]
    out += [f"- `{table}` — {text}" for table, text in SHARED_TABLES.items()]
    out += ["", "Keys in `computed`:", ""]
    out += [f"- `{key}` — {text}" for key, text in COMPUTED.items()]
    out += ["", "## Files maintained by hand", ""]
    out += [f"- `{path}` — {text}" for path, text in CURATED.items()]
    out += [
        "", "## How the sources fit together", "",
        "- **Economies.** `us` is Z.1, `ea` is the ECB accounts, `jp` is the Bank of Japan accounts. `src/fwm/economies/` "
        "gives each its accounts and its context (rates, GDP, announcements) behind one interface; nothing joins their "
        "tables directly. `rate_series`, `rates_daily` and `gdp_quarterly` carry an `economy` column with these ids.",
        "- **Periods.** Quarters are `2026:Q2` everywhere, months `2026-09`, days ISO dates. Daily rates are averaged to "
        "quarters when shown beside the accounts; GDP is summed over four quarters.",
        "- **Units.** Amounts are stored in millions of the source's currency (USD, EUR, JPY). Nothing is converted at "
        "load time; the side-by-side comparison converts at the ECB reference rate on the last day of the quarter.",
        "- **Countries.** The Treasury data uses its own country codes and names, the BIS two-letter codes and the IMF "
        "three-letter codes. `country_codes.csv` is the one place they meet; country pages are keyed by the Treasury name.",
        "- **Cross-border data and the accounts** are separate views of the same world and are not reconciled: the "
        "accounts' rest-of-the-world sector is not broken down by country.",
        "",
    ]
    return "\n".join(out)
