# fwm

An explorable model of the financial system. Design notes: [docs/design1.md](docs/design1.md).

Built so far, mostly from the Federal Reserve's Z.1 financial accounts:

- **Overview**: a map of the whole system (who owes, through which instruments, and who holds), the latest quarter's unusual flows, largest flows and valuation changes, and an index of everything else.
- **Instrument pages**: who holds and who owes each instrument (Treasuries, repo, mortgages, deposits, equities, ...), by sector group and over time.
- **Sector pages**: each sector's full financial balance sheet.
- **Context on every chart**: interest rates (Federal Reserve H.15), markers for Federal Reserve announcements, and amounts as a share of GDP.

Instrument and sector pages link to each other, so you can walk from an instrument to a holder, to that holder's other assets and liabilities, and on to the next instrument.

## Run

```sh
uv run fwm ingest          # download Z.1 and H.15 into data/fwm.duckdb (about a minute)
uv run fwm ingest --only rates   # refresh just the daily interest rates (seconds)
cd web && npm install && npm run build && cd ..
uv run pytest              # accounting checks on the data, and a browser run through the UI
uv run fwm serve           # http://127.0.0.1:8000
```

The browser tests use Playwright with the installed Chrome (or `uv run playwright install chromium`); they are skipped if neither is available.

Every Z.1 release downloaded is also kept under `data/raw/z1/vintages/`, because each release revises earlier quarters and old releases cannot be fetched later.

For UI development, run `uv run fwm serve --reload` and `npm run dev` in `web/` (Vite proxies `/api` to port 8000).

## Layout

- `src/fwm/z1.py`: ingests every Z.1 table into `z1_series` and `z1_observations`, and records the release vintage.
- `src/fwm/structure.py`: infers which lines of each Z.1 table sum to which totals, verified against every quarter.
- `src/fwm/sectors.py`: sector balance sheets as verified trees.
- `src/fwm/instruments.py`: holders and issuers of each instrument, and the shared sector groups used on every page.
- `src/fwm/overview.py`: ranks the latest quarter's flows against each position's own history; computed at ingest.
- `src/fwm/systemmap.py`: amounts owed and held by sector group and instrument family; computed at ingest.
- `src/fwm/rates.py`: daily benchmark interest rates from H.15.
- `src/fwm/context.py`, `src/fwm/events.csv`: rates by quarter, GDP, and a hand-curated calendar of Federal Reserve announcements, each citing its press release.
- `src/fwm/api.py`: HTTP API over the views.
- `web/`: React UI.
- `data/`: downloaded and derived data (not committed).
