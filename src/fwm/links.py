"""Links between economies: who holds whose securities, and what banks in one are owed by the other.

Two sources, both in US dollars and both by pair of countries:

- IMF Portfolio Investment Positions by Counterpart Economy (formerly the Coordinated
  Portfolio Investment Survey): each reporting country's holdings of equity (with fund
  shares) and of debt securities, by the country of the issuer. End of June and December.
- BIS locational banking statistics: claims and liabilities of the banks located in each
  reporting country, by the country of the counterparty. Quarterly, with the part
  denominated in US dollars and in euro.

    xb_positions(kind, denom, period, reporter, counterpart, value)

`reporter` is always the country whose data it is, as an ISO two-letter code (or 5A, the BIS code
for all reporting countries together, the only level at which currencies are published); `counterpart`
keeps the source's own code (three letters in the IMF data, two in the BIS data). Every country in
country_codes.csv is kept as a reporter. `value` is USD millions.

The euro area is not published as one unit for every pair, so it is the sum of its member
countries with positions between members left out. Membership is today's for every date.
"""

from __future__ import annotations

import csv
import datetime as dt
import functools
import json
import re
import unicodedata
import urllib.request
from pathlib import Path

import duckdb

from fwm import ddp

SOURCE_ID = "links"
SOURCE_NAME = "IMF portfolio investment positions and BIS locational banking statistics, by counterpart country"
SOURCE_URL = "https://data.imf.org/en/datasets/IMF.STA:PIP"
IMF_API = ("https://api.imf.org/external/sdmx/3.0/data/dataflow/IMF.STA/PIP/+/"
           "*.A.{indicator}.S1.S1.*.S?c%5BTIME_PERIOD%5D=ge:2001")
BIS_API = ("https://stats.bis.org/api/v2/data/dataflow/BIS/WS_LBS_D_PUB/1.0/"
           "Q.S.{position}.A.TO1+USD+EUR.A.5J.A..A..N?startPeriod=1999-Q1")
BIS_ACCEPT = "application/vnd.sdmx.data+csv;version=1.0.0"

EURO_MEMBERS = {
    "AT": ("AUT", "Austria"), "BE": ("BEL", "Belgium"), "BG": ("BGR", "Bulgaria"), "HR": ("HRV", "Croatia"),
    "CY": ("CYP", "Cyprus"), "EE": ("EST", "Estonia"), "FI": ("FIN", "Finland"), "FR": ("FRA", "France"),
    "DE": ("DEU", "Germany"), "GR": ("GRC", "Greece"), "IE": ("IRL", "Ireland"), "IT": ("ITA", "Italy"),
    "LV": ("LVA", "Latvia"), "LT": ("LTU", "Lithuania"), "LU": ("LUX", "Luxembourg"), "MT": ("MLT", "Malta"),
    "NL": ("NLD", "Netherlands"), "PT": ("PRT", "Portugal"), "SK": ("SVK", "Slovakia"), "SI": ("SVN", "Slovenia"),
    "ES": ("ESP", "Spain"),
}
CODES_PATH = Path(__file__).with_name("country_codes.csv")


@functools.lru_cache(maxsize=1)
def load_codes() -> list[dict]:
    """Every country both sources know: ISO two- and three-letter codes, a short name, and other names it goes by."""
    with CODES_PATH.open(newline="", encoding="utf-8") as source:
        return [dict(row, aliases=[a for a in row["aliases"].split(";") if a]) for row in csv.DictReader(source)]


ISO3 = {"US": "USA", "JP": "JPN", "GB": "GBR", "CN": "CHN", "KY": "CYM", **{code: iso3 for code, (iso3, _) in EURO_MEMBERS.items()}}
COUNTRY_NAMES = {"US": "United States", "JP": "Japan", "GB": "United Kingdom", "CN": "China", "KY": "Cayman Islands",
                 **{code: name for code, (_, name) in EURO_MEMBERS.items()}}
# id, name, member countries. Ids match the economy ids where the economy has its own pages.
AREAS = (
    ("us", "United States", ("US",)),
    ("ea", "Euro area", tuple(EURO_MEMBERS)),
    ("jp", "Japan", ("JP",)),
    ("uk", "United Kingdom", ("GB",)),
    ("cn", "China", ("CN",)),
    ("ky", "Cayman Islands", ("KY",)),
)
AREA_NAMES = {area_id: name for area_id, name, _ in AREAS}
MEMBERS = {area_id: members for area_id, _, members in AREAS}
OTHER, WORLD = "other", "world"
WORLD_CODE = {"imf": "G001", "bis": "5J"}

# kind -> source, file, name, what a row is, what a column is, and the sentence for one cell.
KINDS = (
    ("equity", "imf", "P_F51_P_USD", "Equity & fund shares", "Held by residents of", "Issued in",
     "Residents of {holder} hold {amount} of equity and fund shares issued in {issuer}"),
    ("debt", "imf", "P_F3_P_USD", "Debt securities", "Held by residents of", "Issued in",
     "Residents of {holder} hold {amount} of debt securities issued in {issuer}"),
    ("bank_claims", "bis", "C", "Bank claims", "Banks located in", "Claims on residents of",
     "Banks located in {holder} have {amount} of claims on residents of {issuer}"),
    ("bank_liabilities", "bis", "L", "Bank liabilities", "Banks located in", "Owe to residents of",
     "Banks located in {holder} owe {amount} to residents of {issuer}"),
)
# The portfolio survey was annual until 2013 and has a single early round in 1997.
FIRST = {"imf": "2001:Q4", "bis": "1999:Q1"}
KIND_IDS = tuple(kind[0] for kind in KINDS)
DENOMS = {"TO1": "all", "USD": "usd", "EUR": "eur"}


def _file(kind_id: str) -> str:
    return f"{kind_id}.csv"


def download(raw_dir: Path) -> None:
    raw_dir.mkdir(parents=True, exist_ok=True)
    for kind_id, source, code, *_ in KINDS:
        url = IMF_API.format(indicator=code) if source == "imf" else BIS_API.format(position=code)
        accept = "text/csv" if source == "imf" else BIS_ACCEPT
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": accept})
        with urllib.request.urlopen(request, timeout=600) as response, (raw_dir / _file(kind_id)).open("wb") as out:
            while chunk := response.read(1 << 20):
                out.write(chunk)


def ingest(raw_dir: Path, db_path: Path) -> dict:
    con = duckdb.connect(str(db_path))
    try:
        con.execute("CREATE OR REPLACE TABLE xb_positions (kind VARCHAR, denom VARCHAR, period VARCHAR, reporter VARCHAR, "
                    "counterpart VARCHAR, value DOUBLE)")
        con.execute("CREATE OR REPLACE TEMP TABLE xb_codes (iso2 VARCHAR, iso3 VARCHAR)")
        con.executemany("INSERT INTO xb_codes VALUES (?, ?)", [(row["iso2"], row["iso3"]) for row in load_codes()])
        for kind_id, source, *_ in KINDS:
            path = str(raw_dir / _file(kind_id))
            if source == "imf":
                # Positions are in US dollars. 2025-S1 is the end of June, 2025-S2 the end of December.
                con.execute(
                    "INSERT INTO xb_positions SELECT ?, 'all', "
                    "substr(TIME_PERIOD, 1, 4) || CASE WHEN TIME_PERIOD LIKE '%S1' THEN ':Q2' ELSE ':Q4' END, "
                    "c.iso2, COUNTERPART_COUNTRY, CAST(OBS_VALUE AS DOUBLE) / 1e6 "
                    "FROM read_csv(?, all_varchar = true) JOIN xb_codes c ON c.iso3 = COUNTRY "
                    "WHERE FREQUENCY = 'S' AND OBS_VALUE IS NOT NULL AND OBS_VALUE <> ''", [kind_id, path])
            else:
                con.execute(
                    "INSERT INTO xb_positions SELECT ?, CASE L_DENOM WHEN 'TO1' THEN 'all' WHEN 'USD' THEN 'usd' ELSE 'eur' END, "
                    "replace(TIME_PERIOD, '-', ':'), L_REP_CTY, L_CP_COUNTRY, CAST(OBS_VALUE AS DOUBLE) "
                    "FROM read_csv(?, all_varchar = true) "
                    "WHERE (L_REP_CTY = '5A' OR L_REP_CTY IN (SELECT iso2 FROM xb_codes)) AND OBS_VALUE IS NOT NULL AND OBS_VALUE NOT IN ('', 'NaN')", [kind_id, path])
        con.execute("DELETE FROM xb_positions WHERE isnan(value)")
        rows, latest = con.execute("SELECT count(*), max(period) FROM xb_positions").fetchone()
        if not rows:
            raise RuntimeError("Cross-border downloads hold no values")
        fetched = dt.datetime.fromtimestamp((raw_dir / _file("equity")).stat().st_mtime, dt.timezone.utc)
        ddp.record_release(con, SOURCE_ID, SOURCE_NAME, SOURCE_URL, fetched, latest)
        build(con)
        by_kind = dict(con.execute("SELECT kind, max(period) FROM xb_positions GROUP BY kind").fetchall())
    finally:
        con.close()
    return {"observations": rows, "latest": by_kind}


def available(con: duckdb.DuckDBPyConnection) -> bool:
    return bool(con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name = 'xb_positions'").fetchone()[0])


def _quarters(first: str, last: str) -> list[str]:
    year, quarter = int(first[:4]), int(first[-1])
    out = []
    while f"{year}:Q{quarter}" <= last:
        out.append(f"{year}:Q{quarter}")
        year, quarter = (year, quarter + 1) if quarter < 4 else (year + 1, 1)
    return out


def _kind(con: duckdb.DuckDBPyConnection, kind_id: str, source: str) -> dict:
    """One holder-by-issuer table of series for a kind, areas built from their member countries."""
    world = WORLD_CODE[source]
    code = (lambda iso2: ISO3[iso2]) if source == "imf" else (lambda iso2: iso2)
    wanted = [code(iso2) for iso2 in ISO3] + [world]
    marks = ", ".join("?" for _ in wanted)
    values: dict[tuple[str, str, str], float] = {}
    for period, reporter, counterpart, value in con.execute(
            f"SELECT period, reporter, counterpart, value FROM xb_positions WHERE kind = ? AND denom = 'all' "
            f"AND reporter IN ({', '.join('?' for _ in ISO3)}) AND period >= ? AND counterpart IN ({marks})",
            [kind_id, *ISO3, FIRST[source], *wanted]).fetchall():
        values[(period, reporter, counterpart)] = value
    if not values:
        return {"periods": [], "holders": [], "matrix": {}}
    present = {key[0] for key in values}
    reporting_countries = {key[1] for key in values}
    # Every quarter is listed, so the two sources share a time axis; half-yearly data leaves the quarters between empty.
    periods = _quarters(min(present), max(present))
    recent = periods[-9:-1]

    def series(pairs) -> list[float | None]:
        """Sum over member pairs per period; None where no pair has a value.

        A period is also left empty when clearly fewer pairs report in it than at the dates around it: some
        euro-area members reported only at year ends for a time, and a sum of the rest would read as a fall.
        """
        sums, weights = [], []
        latest: dict[tuple[str, str], float] = {}
        for period in periods:
            found = {(h, c): values[(period, h, c)] for h, c in pairs if (period, h, c) in values}
            sums.append(sum(found.values()) if found else None)
            # How much of the usual total the pairs present stand for, judged by each pair's latest value so far.
            latest.update(found)
            weights.append(sum(abs(latest[pair]) for pair in found) / (sum(abs(v) for v in latest.values()) or 1.0))
        return [None if value is None or weight < 0.9 else value for value, weight in zip(sums, weights)]

    matrix: dict[str, dict] = {}
    holders = []
    for holder in MEMBERS:
        reporters = [h for h in MEMBERS[holder] if h in reporting_countries]
        if not reporters:
            continue
        total = series([(h, world) for h in reporters])
        inside = series([(h, code(c)) for h in reporters for c in MEMBERS[holder] if c != h])
        total = [None if t is None else t - (i or 0.0) for t, i in zip(total, inside)]
        row: dict[str, dict] = {}
        listed: list[float | None] = [None] * len(periods)
        for issuer in MEMBERS:
            if issuer == holder:
                continue
            level = series([(h, code(c)) for h in reporters for c in MEMBERS[issuer]])
            listed = [a if b is None else (a or 0.0) + b for a, b in zip(listed, level)]
            # Member pairs with nothing in the latest period that had a value in the two years before it.
            missing = sorted({COUNTRY_NAMES[h] if len(MEMBERS[holder]) > 1 else COUNTRY_NAMES[c]
                              for h in reporters for c in MEMBERS[issuer]
                              if (periods[-1], h, code(c)) not in values and any((p, h, code(c)) in values for p in recent)})
            row[issuer] = {"level": level, "missing": missing}
        row[WORLD] = {"level": total, "missing": []}
        # Without any country detail there is no remainder to speak of, only the total.
        row[OTHER] = {"level": [None if t is None or l is None else t - l for t, l in zip(total, listed)], "missing": []}
        row["reporting"] = [COUNTRY_NAMES[h] for h in reporters] if len(MEMBERS[holder]) > 1 else None
        matrix[holder] = row
        holders.append(holder)
    return {"periods": periods, "holders": holders, "matrix": matrix}


def _all_banks(con: duckdb.DuckDBPyConnection) -> dict:
    """Claims and liabilities of all reporting banks worldwide towards each economy, by currency."""
    rows = con.execute("SELECT kind, denom, period, counterpart, value FROM xb_positions WHERE reporter = '5A'").fetchall()
    values = {(kind, denom, period, counterpart): value for kind, denom, period, counterpart, value in rows}
    if not values:
        return {"periods": [], "areas": {}}
    present = {key[2] for key in values}
    periods = _quarters(min(present), max(present))

    def series(kind: str, denom: str, codes) -> list[float | None]:
        out = []
        for period in periods:
            found = [values[(kind, denom, period, c)] for c in codes if (kind, denom, period, c) in values]
            out.append(sum(found) if found else None)
        return out

    def block(codes) -> dict:
        return {side: {denom: series(kind, denom, codes) for denom in ("all", "usd", "eur")}
                for side, kind in (("claims", "bank_claims"), ("liabilities", "bank_liabilities"))}

    return {"periods": periods, "areas": {**{area: block(members) for area, members in MEMBERS.items()}, WORLD: block(("5J",))}}


# What each side of a country's table says. {c} is the country.
SIDES = {
    "equity": ("Equity and fund shares held by residents of {c}, by where issued",
               "Equity and fund shares issued in {c}, by where the holder lives"),
    "debt": ("Debt securities held by residents of {c}, by where issued",
             "Debt securities issued in {c}, by where the holder lives"),
    "bank_claims": ("Claims of banks located in {c}, by where the borrower lives",
                    "Claims on residents of {c} of banks located abroad, by where the bank is"),
    "bank_liabilities": ("What banks located in {c} owe abroad, by where the creditor lives",
                         "What banks abroad owe to residents of {c}, by where the bank is"),
}
COUNTRY_NOTES = {
    "reading": "The left table is what {c} itself reports; the right is what other countries report about {c}. Securities "
               "are placed by where the issuer is resident, bank positions by where the bank's office is.",
    "mirror": "The right-hand securities tables add up only the countries that take part in the IMF survey (about 80), "
              "and leave out central banks' reserves, so they understate what the world "
              "holds. Fewer countries report in June than in December; a date is left out of the chart when clearly fewer "
              "report. The bank totals are for all banks reporting to the BIS; the countries listed are those that publish "
              "their positions by country.",
    "custody": "Holdings booked through a financial centre appear as that centre's: a fund in Luxembourg or the Cayman "
               "Islands counts as a holder there, whoever owns the fund.",
}


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()).strip("-")


def find_country(name: str) -> dict | None:
    """The code-table row for a country given by name, another name it goes by, or either ISO code."""
    return _by_name().get(_slug(name))


@functools.lru_cache(maxsize=1)
def _by_name() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for row in load_codes():
        for key in (row["iso3"].lower(), *map(_slug, row["aliases"]), _slug(row["imf_name"]), _slug(row["name"])):
            out.setdefault(key, row)
    # Two-letter codes last, so that a code never shadows a name.
    for row in load_codes():
        out.setdefault(row["iso2"].lower(), row)
    return out


def _steady(sums: list[dict[str, float]]) -> list[float | None]:
    """Per period, the sum over reporters; None where the reporters present stand for under 90% of the usual total."""
    out: list[float | None] = []
    latest: dict[str, float] = {}
    for found in sums:
        latest.update(found)
        weight = sum(abs(latest[key]) for key in found) / (sum(abs(v) for v in latest.values()) or 1.0)
        out.append(sum(found.values()) if found and weight >= 0.9 else None)
    return out


def country(con: duckdb.DuckDBPyConnection, iso2: str, top: int = 10) -> dict | None:
    """One country's cross-border positions: its own report by counterpart, and what others report about it."""
    codes = load_codes()
    row = next((r for r in codes if r["iso2"] == iso2), None)
    if row is None or not available(con):
        return None
    names = {r["iso2"]: r["name"] for r in codes}
    from_iso3 = {r["iso3"]: r["iso2"] for r in codes}
    kinds = []
    for kind_id, source, _, kind_name, *_ in KINDS:
        own_code = row["iso3"] if source == "imf" else iso2
        to_iso2 = (lambda c: from_iso3.get(c)) if source == "imf" else (lambda c: c if c in names else None)
        own_rows = con.execute(
            "SELECT period, counterpart, value FROM xb_positions WHERE kind = ? AND denom = 'all' AND reporter = ? AND period >= ?",
            [kind_id, iso2, FIRST[source]]).fetchall()
        mirror_rows = con.execute(
            "SELECT period, reporter, value FROM xb_positions WHERE kind = ? AND denom = 'all' AND counterpart = ? AND reporter <> ? "
            "AND reporter <> '5A' AND period >= ?", [kind_id, own_code, iso2, FIRST[source]]).fetchall()
        all_banks = {(denom, period): value for denom, period, value in con.execute(
            "SELECT denom, period, value FROM xb_positions WHERE kind = ? AND reporter = '5A' AND counterpart = ?", [kind_id, iso2]).fetchall()}
        present = {r[0] for r in own_rows} | {r[0] for r in mirror_rows} | {period for _, period in all_banks}
        if not present:
            continue
        periods = _quarters(min(present), max(present))
        index = {period: i for i, period in enumerate(periods)}

        def ranked(values: dict[str, float], total: float | None) -> tuple[list[dict], float | None]:
            listed = sorted(((c, v) for c, v in values.items() if v > 0), key=lambda item: -item[1])[:top]
            rest = None if total is None or not listed else total - sum(v for _, v in listed)
            return ([{"iso2": c, "name": names[c], "value": v, "share_pct": None if not total else round(100 * v / total, 1)}
                     for c, v in listed], rest)

        own = None
        own_total: list[float | None] = [None] * len(periods)
        for period, counterpart, value in own_rows:
            if counterpart == WORLD_CODE[source]:
                own_total[index[period]] = value
        if any(v is not None for v in own_total):
            at = max(i for i, v in enumerate(own_total) if v is not None)
            by = {to_iso2(c): v for p, c, v in own_rows if p == periods[at] and to_iso2(c)}
            rows, rest = ranked(by, own_total[at])
            own = {"label": SIDES[kind_id][0].format(c=row["name"]), "period": periods[at], "total": own_total[at], "series": own_total,
                   "top": rows, "everywhere_else": rest, "counterparts": sum(1 for v in by.values() if v > 0)}

        mirror = None
        found: list[dict[str, float]] = [{} for _ in periods]
        for period, reporter, value in mirror_rows:
            found[index[period]][reporter] = value
        summed = _steady(found)
        if source == "bis":
            series = [all_banks.get(("all", period)) for period in periods]
        else:
            series = summed
        if any(v is not None for v in series):
            at = max(i for i, v in enumerate(series) if v is not None)
            rows, rest = ranked(found[at], series[at])
            mirror = {"label": SIDES[kind_id][1].format(c=row["name"]), "period": periods[at], "total": series[at], "series": series,
                      "top": rows, "everywhere_else": rest, "reporters": len(found[at]),
                      **({"in_us_dollars": all_banks.get(("usd", periods[at])), "in_euro": all_banks.get(("eur", periods[at]))}
                         if source == "bis" else {})}
        if own is None and mirror is None:
            continue
        kinds.append({"id": kind_id, "name": kind_name, "source": "IMF" if source == "imf" else "BIS",
                      "frequency": "half-yearly" if source == "imf" else "quarterly", "periods": periods, "own": own, "mirror": mirror})
    if not kinds:
        return None
    return {
        "iso2": iso2, "name": row["name"], "unit": "USD millions", "kinds": kinds,
        "source": {"name": SOURCE_NAME, "imf": "https://data.imf.org/en/datasets/IMF.STA:PIP", "bis": "https://data.bis.org/topics/LBS"},
        "notes": {key: text.format(c=row["name"]) for key, text in COUNTRY_NOTES.items()},
    }


def pair(con: duckdb.DuckDBPyConnection, a: tuple[str, ...], b: tuple[str, ...]) -> list[dict]:
    """Positions between two sets of countries in both directions, per kind: year ends and the latest date."""
    iso3 = {r["iso2"]: r["iso3"] for r in load_codes()}
    out = []
    for kind_id, source, _, kind_name, *_ in KINDS:
        directions = []
        for holders, issuers in ((a, b), (b, a)):
            wanted = [iso3[c] if source == "imf" else c for c in issuers]
            rows = con.execute(
                f"SELECT period, reporter, sum(value) FROM xb_positions WHERE kind = ? AND denom = 'all' AND period >= ? "
                f"AND reporter IN ({', '.join('?' for _ in holders)}) AND counterpart IN ({', '.join('?' for _ in wanted)}) "
                "GROUP BY period, reporter", [kind_id, FIRST[source], *holders, *wanted]).fetchall()
            periods = sorted({r[0] for r in rows})
            found = [{reporter: value for period, reporter, value in rows if period == p} for p in periods]
            series = dict(zip(periods, _steady(found)))
            shown = [p for p in periods if series[p] is not None]
            directions.append({"holders": holders, "issuers": issuers,
                               "history": [{"period": p, "value": series[p]} for p in shown if p.endswith("Q4") or p == shown[-1]][-13:],
                               "reporting": sorted(found[periods.index(shown[-1])]) if shown else []})
        out.append({"id": kind_id, "name": kind_name, "source": "IMF" if source == "imf" else "BIS", "directions": directions})
    return out


def compute(con: duckdb.DuckDBPyConnection) -> dict:
    kinds = []
    for kind_id, source, _, name, row_label, column_label, sentence in KINDS:
        table = _kind(con, kind_id, source)
        reporting = {holder: table["matrix"][holder].pop("reporting") for holder in table["holders"]}
        kinds.append({"id": kind_id, "name": name, "source": "IMF" if source == "imf" else "BIS", "row_label": row_label,
                      "column_label": column_label, "sentence": sentence, "frequency": "half-yearly" if source == "imf" else "quarterly",
                      "reporting": {holder: names for holder, names in reporting.items() if names}, **table})
    all_banks = _all_banks(con)
    return {
        "areas": [{"id": area_id, "name": name, "has_pages": area_id in ("us", "ea", "jp")} for area_id, name, _ in AREAS],
        "columns": [*MEMBERS, OTHER, WORLD],
        "column_names": {**AREA_NAMES, OTHER: "Everywhere else", WORLD: "All economies"},
        "kinds": kinds,
        "all_banks": all_banks,
        "unit": "USD millions",
        "source": {"name": SOURCE_NAME, "imf": "https://data.imf.org/en/datasets/IMF.STA:PIP", "bis": "https://data.bis.org/topics/LBS"},
        "notes": {
            "reading": "Each number is one economy's claim on another, as reported by the economy in the row. Securities are "
                       "placed by where the issuer is resident; bank positions by where the bank's office is located, whoever "
                       "owns the bank.",
            "euro_area": "The euro area is the sum of its 21 member countries, with positions between members left out, and "
                         "with today's membership at every date. Croatia does not report portfolio holdings, and eight "
                         "smaller members do not report bank positions, so euro-area rows are slightly low. Members began "
                         "publishing bank positions by country at different dates (Spain in 2012, Italy in 2014), which "
                         "shows as steps in the euro-area bank lines; a period is left empty when a large member is missing.",
            "gaps": "China and the Cayman Islands report bank positions only in total, not by country, so they have no rows "
                    "in the bank tables. A dagger marks a number that leaves out a country pair published in earlier periods, "
                    "usually because it is confidential.",
            "custody": "Holdings booked through a financial centre appear as claims on that centre: a US investor's stake in a "
                       "Cayman fund that owns Japanese shares is a claim on the Cayman Islands here, not on Japan.",
            "not_included": "Direct investment, loans by non-banks, derivatives and central banks' reserves (which the "
                            "portfolio survey reports only in total) are not in these tables, so they are not the whole of "
                            "what one economy owes another.",
            "against_us_data": "Compared with the US Treasury's own country data for the same date (end-2025): US holdings "
                               "abroad agree, and so do Japanese and euro-area holdings of US equities. Their holdings of "
                               "US debt are lower here ($1.2T against $1.8T for Japan, $3.1T against $4.4T for the euro "
                               "area), mainly because central banks' reserves are not in the portfolio survey. The United "
                               "Kingdom is lower here and the Cayman Islands higher, because the Treasury data counts "
                               "securities where they are held in custody and this counts them by the owner's residence.",
            "dollars": "Everything is converted to US dollars by the source, whatever currency it is denominated in.",
            "all_banks": "Banks in all countries that report to the BIS, taken together, and their cross-border positions "
                         "with residents of each economy. This is the only level at which the BIS publishes the currency. "
                         "For the euro area it includes positions of banks in one member with residents of another.",
        },
    }


def build(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("CREATE TABLE IF NOT EXISTS computed (key VARCHAR PRIMARY KEY, value VARCHAR)")
    con.execute("DELETE FROM computed WHERE key = 'links'")
    con.execute("INSERT INTO computed VALUES ('links', ?)", [json.dumps(compute(con))])


def view(con: duckdb.DuckDBPyConnection) -> dict | None:
    if not available(con):
        return None
    row = con.execute("SELECT value FROM computed WHERE key = 'links'").fetchone()
    return json.loads(row[0]) if row else compute(con)
