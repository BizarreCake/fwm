# fwm

An explorable model of the financial system. Design notes: [docs/design1.md](docs/design1.md).

Built so far, mostly from the Federal Reserve's Z.1 financial accounts:

- **Overview**: a map of the whole system (who owes, through which instruments, and who holds), the latest quarter's unusual flows, largest flows and valuation changes, and an index of everything else.
- **Instrument pages**: who holds and who owes each instrument (Treasuries, repo, mortgages, deposits, equities, ...), by sector group and over time.
- **Sector pages**: each sector's full financial balance sheet.
- **Federal Reserve, weekly**: the Fed's balance sheet every Wednesday (H.4.1), which runs months past the latest quarter of accounts.
- **Foreign holders by country**: the "rest of the world" split by country each month (Treasury TIC) for Treasuries, agency bonds, corporate bonds and equities, with official against private holders.
- **Countries**: each country as a counterparty of the US: the US securities held there, and its securities held by US residents. Not the country's own accounts.
- **Euro area**: a second full economy, in euro, from ECB data: the same overview, sector and instrument pages as the US from 1999, plus who holds whose paper (which the US accounts cannot show), ECB rates and announcements, and the Eurosystem's balance sheet every week. Switch economies at the top of the overview.
- **Links between economies**: who holds whose securities and what banks in one economy owe and are owed by another, for the US, euro area, Japan, UK, China and the Cayman Islands, with dollars lent outside the US (`#/links`).
- **Side by side**: the two economies compared by instrument and by holder, as a share of each one's GDP or in dollars.
- **Assistant**: a chat panel that answers questions from the same data, links to the pages behind its numbers, and says when the data cannot answer.
- **Context on every chart**: interest rates (Federal Reserve H.15), markers for Federal Reserve announcements, and amounts as a share of GDP.

Instrument and sector pages link to each other, so you can walk from an instrument to a holder, to that holder's other assets and liabilities, and on to the next instrument.

## Run

```sh
uv run fwm ingest          # download Z.1, H.15, H.4.1, TIC and the ECB accounts into data/fwm.duckdb (a few minutes)
uv run fwm ingest --only rates        # refresh just the daily interest rates (seconds)
uv run fwm ingest --only fed-weekly   # refresh just the weekly Fed balance sheet (seconds)
uv run fwm ingest --only tic          # refresh just foreign holdings by country (seconds)
uv run fwm ingest --only ecb          # refresh everything for the euro area: accounts, rates, GDP, weekly Eurosystem (under a minute)
uv run fwm ingest --only links        # refresh positions between economies (IMF and BIS; about four minutes)
cd web && npm install && npm run build && cd ..
uv run pytest              # accounting checks on the data, and a browser run through the UI
uv run fwm serve           # http://127.0.0.1:8000
```

The browser tests use Playwright with the installed Chrome (or `uv run playwright install chromium`); they are skipped if neither is available.

Every Z.1 release downloaded is also kept under `data/raw/z1/vintages/`, because each release revises earlier quarters and old releases cannot be fetched later.

The assistant needs a model, reached one of two ways. Everything else works without either.

- **Claude Code (default if installed):** if the `claude` CLI is installed and logged in, the assistant runs each question as a headless Claude Code session on that login, so usage counts against your Claude subscription. The model is set by this project (Claude Opus 5.5), not by Claude Code's own default. The session gets only this project's tools, through a local MCP server (`fwm.mcp_server`); Claude Code's file, shell and web tools and your Claude Code settings are switched off. This is for your own use on your own machine.
- **Anthropic API:** set `ANTHROPIC_API_KEY` before `fwm serve` and the assistant calls the API instead (Claude Opus 5.5 by default).

`FWM_AGENT_BACKEND=claude-code|api` forces one.

```sh
uv run fwm ask "Who holds US Treasuries?"   # one question from the command line
uv run fwm bench --list                     # the benchmark questions
uv run fwm bench                            # run them against the model and grade the answers (uses subscription or API credit)
```

`FWM_AGENT_MODEL` and `FWM_AGENT_EFFORT` override the model and effort level on either backend. The chat panel shows the model in its header and under each answer.

## QuantConnect data

`qcbridge`, a separate package in `src/qcbridge` that does not depend on the rest of this project, runs a code snippet inside a QuantConnect research notebook and brings back the result, for pulling small datasets from sources QuantConnect is connected to.

```sh
uv run qcbridge worker       # prints a notebook cell; paste it into a QuantConnect research notebook and run it (once per notebook session)
uv run qcbridge run snippet.py                 # runs the snippet there; saves its last expression to data/qc/snippet.parquet
uv run qcbridge run -c "qb.history(qb.add_equity('SPY').symbol, 30, Resolution.DAILY)" -o spy.parquet
```

A snippet's result is the value of its last expression: a DataFrame or Series is saved as parquet, anything else is printed. A snippet can read the notebook's variables, so `qb` is there (the worker creates it if the notebook has not), but what the snippet itself assigns is discarded when it finishes, so that a long session does not fill the kernel's memory. `--keep` leaves its variables in the notebook for later snippets. Each run prints how much of the notebook's memory is in use, and a result too large to send within what is left is refused. After changing `worker.py`, `uv run qcbridge update` replaces the running worker without re-pasting the cell.

The notebook worker dials out to a proxy host, and each `qcbridge run` opens a reverse SSH tunnel from that proxy to this machine for as long as the job takes. Defaults are in `src/qcbridge/__init__.py`; `FWM_QC_PROXY` (`user@host`), `FWM_QC_PORT` and `FWM_QC_KEY` override them. The proxy's sshd needs `GatewayPorts yes` and the port must be open to the internet. The worker and this machine authenticate each other with the secret in `keys/qc_token`, and every message is signed, but nothing is encrypted between QuantConnect and the proxy. `keys/` is not committed.

For UI development, run `uv run fwm serve --reload` and `npm run dev` in `web/` (Vite proxies `/api` to port 8000).

## Layout

- `src/fwm/z1.py`: ingests every Z.1 table into `z1_series` and `z1_observations`, and records the release vintage.
- `src/fwm/structure.py`: infers which lines of each Z.1 table sum to which totals, verified against every quarter.
- `src/fwm/sectors.py`: sector balance sheets as verified trees.
- `src/fwm/instruments.py`: holders and issuers of each instrument, and the shared sector groups used on every page.
- `src/fwm/overview.py`: ranks the latest quarter's flows against each position's own history; computed at ingest.
- `src/fwm/systemmap.py`: amounts owed and held by sector group and instrument family; computed at ingest.
- `src/fwm/rates.py`: daily benchmark interest rates from H.15.
- `src/fwm/fedweekly.py`: the Federal Reserve's weekly balance sheet from H.4.1, arranged so each side adds up to the published total.
- `src/fwm/tic.py`: foreign holders of US securities by country from the Treasury's TIC reports, checked against Z.1's rest-of-the-world totals.
- `src/qcbridge/`: the QuantConnect bridge, independent of `fwm`; `worker.py` is what gets pasted into the notebook.
- `src/fwm/countries.py`: one country's securities links with the US in both directions.
- `src/fwm/economies.py`: the economies with full accounts (US and euro area), and candidates checked for later. Pages and API paths carry the economy id (`#/us/sector/S121`, `#/ea/sector/S1M`, `/api/economy/ea/sectors`).
- `src/fwm/ecb.py`: ingests the ECB's quarterly sector accounts for the euro area into `qsa_series` and `qsa_observations`.
- `src/fwm/euroarea.py`: the euro area's sector and instrument views, in the same shapes as the US ones, and who holds whose paper.
- `src/fwm/eacontext.py`: euro-area rates, GDP, ECB announcements (`events_ea.csv`) and the dollar exchange rate.
- `src/fwm/euweekly.py`: the Eurosystem's weekly balance sheet, in the same shape as the weekly Fed data.
- `src/fwm/links.py`: positions between economies from the IMF's portfolio survey and the BIS banking statistics.
- `src/fwm/compare.py`: the economies side by side, in dollars and as a share of GDP.
- `src/fwm/ddp.py`: reader for the Fed's download packages (H.15, H.4.1).
- `src/fwm/context.py`, `src/fwm/events.csv`: rates by quarter, GDP, and a hand-curated calendar of Federal Reserve announcements, each citing its press release.
- `src/fwm/tools.py`: the assistant's tools, wrapping the same queries the pages use.
- `src/fwm/agent.py`: the assistant's instructions, and the two ways of reaching the model.
- `src/fwm/mcp_server.py`: the same tools served to Claude Code over MCP.
- `src/fwm/bench.py`: benchmark questions with answers computed from the data, and their grader.
- `src/fwm/api.py`: HTTP API over the views.
- `web/`: React UI.
- `data/`: downloaded and derived data (not committed).
