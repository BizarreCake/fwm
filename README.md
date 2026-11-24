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
- **Japan**: a third full economy, in yen, from the Bank of Japan's flow of funds since 1997, with the Bank of Japan as its own sector, who holds government bonds, rates, GDP and announcements.
- **Any country and the rest of the world**: each country page shows its securities and bank positions with every other country, from its own report and from what others report about it.
- **Links between economies**: who holds whose securities and what banks in one economy owe and are owed by another, for the US, euro area, Japan, UK, China and the Cayman Islands, with dollars lent outside the US (`#/links`).
- **Side by side**: the three economies compared by instrument and by holder, as a share of each one's GDP or in dollars.
- **Assistant**: a chat panel that answers questions from the same data, links to the pages behind its numbers, and says when the data cannot answer.
- **Context on every chart**: interest rates (Federal Reserve H.15), markers for Federal Reserve announcements, and amounts as a share of GDP.

Instrument and sector pages link to each other, so you can walk from an instrument to a holder, to that holder's other assets and liabilities, and on to the next instrument.

## Run

Every source, its tables, how often it is published and how to refresh it are described in [docs/sources.md](docs/sources.md), which is written from the registry in `src/fwm/sources.py`.

```sh
uv run fwm ingest          # download every source into data/fwm.duckdb (several minutes)
uv run fwm status          # what is loaded from each source, and which have newer data out
uv run fwm ingest --only rates        # refresh one group: z1, rates, fed-weekly, tic, ecb, boj or links
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

```
src/fwm/
  cli.py            the `fwm` command: ingest, status, sources, serve, ask, bench
  api.py            HTTP API over the views
  sources.py        the registry of sources: tables, releases, frequency, how to refresh
  paths.py          where the database, downloads and curated files live
  codes.py          country codes shared by the Treasury, BIS and IMF data
  curated/          files maintained by hand: central bank announcements, country codes
  loaders/          one module per source, named after its id in the registry:
                    download it and load it into DuckDB, nothing else
  economies/        one folder per economy with full accounts, each with the same parts
    __init__.py       the lookup: accounts, context, weekly data and periods by economy id
    base.py           the rates, GDP and exchange-rate tables all economies share
    us/               sectors, instruments, structure (Z.1), context, weekly (H.4.1)
    ea/               accounts (ECB QSA), context, weekly (Eurosystem)
    jp/               accounts (Bank of Japan flow of funds), context
  views/            views across sources or economies: overview, system map, comparison,
                    foreign holders (TIC), countries, links between economies
  assistant/        instructions and model access (agent), benchmark, MCP server
    tools/            the assistant's tools by subject, and their registry
```

Dependencies run one way: loaders know nothing of views or the assistant; economies and views read what loaders stored; the assistant and the API sit on top. A new economy is a folder under `economies/`, a loader, and entries in `economies/__init__.py` and `sources.py`.

- `web/`: React UI.
- `data/`: downloaded and derived data (not committed).
