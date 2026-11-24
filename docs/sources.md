# Data sources and database

Written from `src/fwm/sources.py` by `uv run fwm sources --write`. Edit the registry, not this file.
For what each source can and cannot say, and what is wanted next, see `docs/data.md`.

## Keeping the data fresh

- `uv run fwm status` lists every release: the latest period loaded, when it was loaded, when the next period is usually published, and whether that date has passed.
- `uv run fwm ingest` downloads and loads everything. `uv run fwm ingest --only <name>` refreshes one group (z1, rates, fed-weekly, tic, ecb, boj, links) or one source by its id below.
- `--no-download` reloads from the files already in `data/raw`, which is what to use after changing a loader.
- Every load replaces that source's tables in full, so a refresh also picks up revisions to past periods.
- The publication lags below are approximate; they only drive the hint in `fwm status`.

| Source id | Refresh with | Release | Frequency | Usual lag |
| --- | --- | --- | --- | --- |
| `z1` | `--only z1` | US financial accounts | quarter | 75 days |
| `rates` | `--only rates` | US interest rates | day | 3 days |
| `fed-weekly` | `--only fed-weekly` | Weekly Fed balance sheet | week | 2 days |
| `tic` | `--only tic` | US long-term securities held by foreigners | month | 50 days |
| `tic` | `--only tic` | Foreign long-term securities held by US residents | month | 50 days |
| `tic` | `--only tic` | Treasury securities held by foreigners | month | 50 days |
| `ecb-weekly` | `--only ecb` | Weekly Eurosystem balance sheet | week | 5 days |
| `ecb-context` | `--only ecb` | Euro-area interest rates | day | 3 days |
| `ecb-context` | `--only ecb` | Euro-area GDP | quarter | 70 days |
| `ecb-context` | `--only ecb` | US dollars per euro | day | 3 days |
| `ecb-accounts` | `--only ecb` | Euro-area financial accounts | quarter | 120 days |
| `jp-context` | `--only boj` | Bank of Japan policy rate (BIS) | day | 10 days |
| `jp-context` | `--only boj` | Japanese government bond yields (Ministry of Finance) | day | 3 days |
| `jp-context` | `--only boj` | Japanese GDP (OECD) | quarter | 50 days |
| `jp-context` | `--only boj` | Yen per euro (ECB) | day | 3 days |
| `boj-accounts` | `--only boj` | Japan's financial accounts | quarter | 80 days |
| `links` | `--only links` | Portfolio holdings by country pair (IMF) | half-year | 300 days |
| `links` | `--only links` | Bank positions by country pair (BIS) | quarter | 120 days |

## Sources

### Federal Reserve Z.1, Financial Accounts of the United States (`z1`)

- **Publisher:** Federal Reserve Board. <https://www.federalreserve.gov/releases/z1/>
- **Covers:** US sector balance sheets and instruments, quarterly from 1952:Q1, in US dollars. Also US nominal GDP.
- **Refresh:** `uv run fwm ingest --only z1`.
- **Loader:** `src/fwm/loaders/z1.py`; downloads go to `data/raw/z1/`.
- **Releases recorded:** `fed_z1` (quarter; `published_at` is the release time).
- **Past downloads:** Each release is kept as data/raw/z1/vintages/z1_<publication date>.zip.
- **Rebuilds:** `overview`, `system_map` in `computed`.
- **Tables:**
  - `z1_series` — series_id, description, unit, table_id, table_name, line: one row per series in each table it appears in
  - `z1_observations` — series_id, period, period_end, value: one value per series and quarter, USD millions
  - `z1_structure` — table_id, series_id, position, parent_series_id, role: the line hierarchy of each table
- Series ids carry a measure prefix: FL levels, FU transactions, FR revaluations, FV other changes.

### Federal Reserve H.15, Selected Interest Rates (`rates`)

- **Publisher:** Federal Reserve Board. <https://www.federalreserve.gov/releases/h15/>
- **Covers:** Daily fed funds rate and 3-month, 2-year and 10-year Treasury yields.
- **Refresh:** `uv run fwm ingest --only rates` (seconds).
- **Loader:** `src/fwm/loaders/rates.py`; downloads go to `data/raw/h15/`.
- **Releases recorded:** `fed_h15` (day; `published_at` is the release time).
- **Past downloads:** not kept; each refresh replaces the files.
- **Fills its rows of the shared tables:** `rate_series`, `rates_daily`.
- Its rows are economy `us`.

### Federal Reserve H.4.1, Factors Affecting Reserve Balances (`fed-weekly`)

- **Publisher:** Federal Reserve Board. <https://www.federalreserve.gov/releases/h41/>
- **Covers:** The Fed's balance sheet every Wednesday from December 2002, in US dollars.
- **Refresh:** `uv run fwm ingest --only fed-weekly` (seconds).
- **Loader:** `src/fwm/loaders/fed_weekly.py`; downloads go to `data/raw/h41/`.
- **Releases recorded:** `fed_h41` (week; `published_at` is the release time).
- **Past downloads:** not kept; each refresh replaces the files.
- **Tables:**
  - `weekly_series` — series_id, source, description: the H.4.1 series loaded
  - `weekly_observations` — series_id, date, value: Wednesday levels, USD millions

### US Treasury TIC, SLT Tables 1, 2 and 3 (`tic`)

- **Publisher:** US Department of the Treasury. <https://home.treasury.gov/data/treasury-international-capital-tic-system>
- **Covers:** Foreign holdings of US securities and US holdings of foreign securities, by country, monthly from January 2020.
- **Refresh:** `uv run fwm ingest --only tic` (seconds).
- **Loader:** `src/fwm/loaders/tic.py`; downloads go to `data/raw/tic/`.
- **Releases recorded:** `treasury_tic_slt1` (month; `published_at` is the download time); `treasury_tic_slt2` (month; `published_at` is the download time); `treasury_tic_slt3` (month; `published_at` is the download time).
- **Past downloads:** Each month's files are kept as data/raw/tic/vintages/slt_table<n>_<month>.txt.
- **Read together with:** `links`.
- **Tables:**
  - `tic_country` — source, code, name, kind, region, position: the countries and groups in each table, with the Treasury's own codes
  - `tic_holdings` — asset, code, month, total, total_net, long_term, long_term_net, long_term_valuation, short_term, short_term_net: holdings and monthly net purchases, USD millions
- Country pages are keyed by the Treasury's country names; src/fwm/curated/country_codes.csv ties them to ISO codes.

### ECB, Weekly financial statement of the Eurosystem (ILM) (`ecb-weekly`)

- **Publisher:** European Central Bank. <https://data.ecb.europa.eu/data/datasets/ILM>
- **Covers:** The Eurosystem's balance sheet every Friday from January 1999, in euro.
- **Refresh:** `uv run fwm ingest --only ecb` (under a minute for the whole ecb group), or `--only ecb-weekly` for this source alone.
- **Loader:** `src/fwm/loaders/ecb_weekly.py`; downloads go to `data/raw/ecb/weekly/`.
- **Releases recorded:** `ecb_weekly` (week; `published_at` is the download time).
- **Past downloads:** not kept; each refresh replaces the files.
- **Tables:**
  - `eurosystem_weekly` — series_id, date, value: Friday levels, EUR millions

### ECB key interest rate, yield curve, GDP and dollar exchange rate (`ecb-context`)

- **Publisher:** European Central Bank. <https://data.ecb.europa.eu/>
- **Covers:** Deposit facility rate and AAA government yields (daily), euro-area nominal GDP (quarterly), US dollars per euro (daily).
- **Refresh:** `uv run fwm ingest --only ecb`, or `--only ecb-context` for this source alone.
- **Loader:** `src/fwm/loaders/ecb_context.py`; downloads go to `data/raw/ecb/context/`.
- **Releases recorded:** `ecb_rates` (day; `published_at` is the download time); `ecb_gdp` (quarter; `published_at` is the download time); `ecb_fx` (day; `published_at` is the download time).
- **Past downloads:** not kept; each refresh replaces the files.
- **Fills its rows of the shared tables:** `rate_series`, `rates_daily`, `gdp_quarterly`, `fx_daily`.
- Its rows are economy `ea` and exchange-rate pair `USD/EUR` (US dollars per euro), the only dollar rate in the database. GDP is not seasonally adjusted.

### ECB, Quarterly Sector Accounts for the euro area (QSA) (`ecb-accounts`)

- **Publisher:** European Central Bank. <https://data.ecb.europa.eu/data/datasets/QSA>
- **Covers:** Euro-area sector balance sheets, instruments and who-holds-whose detail, quarterly from 1999:Q1, in euro.
- **Refresh:** `uv run fwm ingest --only ecb`, or `--only ecb-accounts` for this source alone.
- **Loader:** `src/fwm/loaders/ecb_accounts.py`; downloads go to `data/raw/ecb/`.
- **Releases recorded:** `ecb_qsa` (quarter; `published_at` is the download time).
- **Past downloads:** Each download is kept as data/raw/ecb/vintages/qsa_I10_<latest quarter>_<download date>.csv.gz.
- **Rebuilds:** `overview:ea`, `system_map:ea` in `computed`.
- **Read together with:** `ecb-context`.
- **Tables:**
  - `qsa_series` — key, counterpart_area, sector, counterpart_sector, side, measure, instrument, maturity: the ECB series key split into its dimensions
  - `qsa_observations` — key, period, value: one value per series and quarter, EUR millions

### Japan: policy rate, government bond yields, GDP and yen exchange rate (`jp-context`)

- **Publisher:** BIS, Ministry of Finance of Japan, OECD, ECB. <https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/index.htm>
- **Covers:** Bank of Japan policy rate (BIS, daily), 2- and 10-year government bond yields (Ministry of Finance, daily), nominal GDP (OECD, quarterly), yen per euro (ECB, daily).
- **Refresh:** `uv run fwm ingest --only boj` (under a minute for the whole boj group), or `--only jp-context` for this source alone.
- **Loader:** `src/fwm/loaders/jp_context.py`; downloads go to `data/raw/boj/context/`.
- **Releases recorded:** `jp_policy_rate` (day; `published_at` is the download time); `jp_yields` (day; `published_at` is the download time); `jp_gdp` (quarter; `published_at` is the download time); `jp_fx` (day; `published_at` is the download time).
- **Past downloads:** not kept; each refresh replaces the files.
- **Read together with:** `ecb-context`.
- **Fills its rows of the shared tables:** `rate_series`, `rates_daily`, `gdp_quarterly`, `fx_daily`.
- Its rows are economy `jp` and exchange-rate pair `JPY/EUR` (yen per euro). GDP is seasonally adjusted.
- Dollars per yen is the `USD/EUR` rate divided by the `JPY/EUR` rate for the same day, so it needs the ecb group loaded.

### Bank of Japan, Flow of Funds Accounts (`boj-accounts`)

- **Publisher:** Bank of Japan. <https://www.boj.or.jp/en/statistics/sj/index.htm>
- **Covers:** Japan's sector balance sheets and instruments, quarterly from 1997:Q4, in yen.
- **Refresh:** `uv run fwm ingest --only boj`, or `--only boj-accounts` for this source alone.
- **Loader:** `src/fwm/loaders/boj_accounts.py`; downloads go to `data/raw/boj/`.
- **Releases recorded:** `boj_fof` (quarter; `published_at` is the release time).
- **Past downloads:** Each file is kept as data/raw/boj/vintages/fof-<date the Bank prepared it>.zip.
- **Rebuilds:** `overview:jp`, `system_map:jp` in `computed`.
- **Read together with:** `jp-context`.
- **Tables:**
  - `jff_observations` — series_id, period, value: one value per series and quarter, JPY millions
- Series ids are FOF_FFA + S, F or R (stock, flow, reconciliation) + sector + A or L + item.

### IMF portfolio investment positions and BIS locational banking statistics (`links`)

- **Publisher:** International Monetary Fund, Bank for International Settlements. <https://data.imf.org/en/datasets/IMF.STA:PIP>
- **Covers:** Positions between pairs of countries in US dollars: holdings of equity and of debt securities (IMF, end of June and December from 2001), and bank claims and liabilities (BIS, quarterly from 1999).
- **Refresh:** `uv run fwm ingest --only links` (about four minutes).
- **Loader:** `src/fwm/loaders/links.py`; downloads go to `data/raw/links/`.
- **Releases recorded:** `imf_pip` (half-year; `published_at` is the download time); `bis_lbs` (quarter; `published_at` is the download time).
- **Past downloads:** not kept; each refresh replaces the files.
- **Rebuilds:** `links` in `computed`.
- **Tables:**
  - `xb_positions` — kind, denom, period, reporter, counterpart, value: one position of a reporting country towards a counterpart, USD millions
- reporter is an ISO two-letter code (or 5A, all BIS reporting countries); counterpart keeps the source's own code: three letters in IMF rows, two in BIS rows. src/fwm/curated/country_codes.csv maps between them.
- Past downloads are not kept: each refresh replaces the four files.

## Tables that belong to no single source

- `rate_series` — economy, series_id, name, short_name, source_series, shown: the interest rates loaded for each economy
- `rates_daily` — economy, series_id, date, value: percent per year
- `gdp_quarterly` — economy, period, value: nominal GDP per quarter, millions of the economy's currency
- `fx_daily` — pair, date, value: ECB reference rates, units of the first currency per euro
- `source_release` — source_id, name, url, published_at, ingested_at, latest_period: one row per release above, written at each load
- `computed` — key, value: results worked out once at load time and stored as JSON

Keys in `computed`:

- `overview` — The US overview page: unusual and largest flows of the latest quarter.
- `system_map` — The US system map: what each sector group holds of each instrument family, every quarter.
- `overview:ea` — The same overview for the euro area.
- `system_map:ea` — The same map for the euro area.
- `overview:jp` — The same overview for Japan.
- `system_map:jp` — The same map for Japan.
- `links` — The tables of positions between the six large economies.

## Files maintained by hand

- `src/fwm/curated/events.csv` — Federal Reserve announcements shown on US charts. Add a row with the date, kind, title, detail and press release.
- `src/fwm/curated/events_ea.csv` — ECB announcements, the same way.
- `src/fwm/curated/events_jp.csv` — Bank of Japan announcements, the same way. Titles follow the Bank's own release titles.
- `src/fwm/curated/country_codes.csv` — ISO two- and three-letter codes, names and other names for 249 countries. Built once from the IMF and BIS code lists by scripts/make_country_codes.py and corrected by hand; edit it directly.

## How the sources fit together

- **Economies.** `us` is Z.1, `ea` is the ECB accounts, `jp` is the Bank of Japan accounts. `src/fwm/economies/` gives each its accounts and its context (rates, GDP, announcements) behind one interface; nothing joins their tables directly. `rate_series`, `rates_daily` and `gdp_quarterly` carry an `economy` column with these ids.
- **Periods.** Quarters are `2026:Q2` everywhere, months `2026-09`, days ISO dates. Daily rates are averaged to quarters when shown beside the accounts; GDP is summed over four quarters.
- **Units.** Amounts are stored in millions of the source's currency (USD, EUR, JPY). Nothing is converted at load time; the side-by-side comparison converts at the ECB reference rate on the last day of the quarter.
- **Countries.** The Treasury data uses its own country codes and names, the BIS two-letter codes and the IMF three-letter codes. `country_codes.csv` is the one place they meet; country pages are keyed by the Treasury name.
- **Cross-border data and the accounts** are separate views of the same world and are not reconciled: the accounts' rest-of-the-world sector is not broken down by country.
