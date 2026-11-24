# fwm

An explorable model of the financial system. Design notes: [docs/design1.md](docs/design1.md).

Built so far, from the Federal Reserve's Z.1 financial accounts:

- **Instrument pages**: who holds and who owes each instrument (Treasuries, repo, mortgages, deposits, equities, ...), by sector group and over time.
- **Sector pages**: each sector's full financial balance sheet.

The two link to each other, so you can walk from an instrument to a holder, to that holder's other assets and liabilities, and on to the next instrument.

## Run

```sh
uv run fwm ingest          # download the current Z.1 release into data/fwm.duckdb (about a minute)
uv run pytest              # accounting checks against the ingested data
cd web && npm install && npm run build && cd ..
uv run fwm serve           # http://127.0.0.1:8000
```

For UI development, run `uv run fwm serve --reload` and `npm run dev` in `web/` (Vite proxies `/api` to port 8000).

## Layout

- `src/fwm/z1.py`: ingests every Z.1 table into `z1_series` and `z1_observations`, and records the release vintage.
- `src/fwm/structure.py`: infers which lines of each Z.1 table sum to which totals, verified against every quarter.
- `src/fwm/sectors.py`: sector balance sheets as verified trees.
- `src/fwm/instruments.py`: holders and issuers of each instrument, and the shared sector groups used on every page.
- `src/fwm/api.py`: HTTP API over the views.
- `web/`: React UI.
- `data/`: downloaded and derived data (not committed).
