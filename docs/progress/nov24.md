# Progress, 24 November 2026

Where the project stands after the work since commit `b80b87e` (interest rates, Fed announcements and GDP scaling).
`docs/data.md` is the running list of sources; this note is the snapshot of what was built and what is open.

## What was added

### An assistant that answers from the data

A chat panel on every page. It works only through tools that read the same data as the pages, links to the page behind
each number, and flags a gap when the data cannot answer what was asked. Two backends (the Anthropic API, or headless
Claude Code through an MCP server), model pinned to `claude-opus-5-5`. A benchmark (`uv run fwm bench`) asks fixed
questions and grades the answers mechanically: stated amounts against the database, links against real pages, cited
series against what the tools returned, and gaps flagged where they should be.

### The Federal Reserve's balance sheet, weekly (H.4.1)

Every Wednesday from 2002-12-18 to 2026-11-18, which runs months past the latest quarter of accounts. Own page
(`#/us/weekly/fed`), a strip on the overview, and two assistant tools. Securities are at face value here and at market
value in Z.1, so the two are never subtracted from each other.

### Foreign holders by country (Treasury TIC)

Monthly from January 2020, for Treasuries, agency bonds, corporate bonds and equities, with official against private
holders (`#/us/foreign/<asset>`). Treasuries match Z.1's rest-of-the-world total at quarter ends to within 0.5%.
Countries are where securities are held in custody, not always where the owner lives; pages and the assistant say so.

### Countries as counterparties of the US

One page per country, plus the euro area and EU (`#/country/<slug>`), with both directions: US securities held there,
and that country's securities held by US residents. This is the country seen from the US, not its own balance sheet.

### Economy-scoped pages and API

Pages and API paths carry an economy id (`#/us/sector/S121`, `/api/economy/us/sectors`). Links made before this
redirect.

### The euro area as a second full economy

From the ECB's quarterly sector accounts (dataset QSA), 1999:Q1 to 2026:Q2, in euro.

- Balance sheets for eight sectors plus the rest of the world, and holders and issuers of seven instruments, on the
  same pages as the US (`#/ea`, `#/ea/sector/S1M`, `#/ea/instrument/F3`), with an economy switch on both overviews.
- The assistant's sector, instrument and history tools take `economy: "ea"` and answer in euro.
- `uv run fwm ingest --only ecb` downloads and loads it in about 25 seconds and keeps each release as a vintage.

How it differs from the US side:

- Banks, central banks and money market funds are one sector, the only split with history to 1999. The Eurosystem and
  other banks are separate from 2015 and shown as parts.
- The rest of the world is derived from residents' positions against non-residents; the ECB does not publish it as a
  sector.
- Derivatives are published net, so have no holders page.
- Nothing is converted to dollars.

## Checks

- Test suite: 145 passed, 2 skipped (the skips are in `tests/test_qcbridge.py` and need pandas).
- Euro-area accounting, every quarter: sectors add up to the whole economy, lines to their parts, and the change in an
  amount equals transactions plus other changes.
- Benchmark, live: the six euro-area questions pass, as did the weekly (7/7) and country (7/7, 6/6) subsets when they
  were added. The full benchmark has not been rerun since the system prompt was last changed.

## Known problems

- **Euro-area fund shares do not balance.** Holders show €25.2T against €23.1T owed. The €2.1T difference is money
  market fund shares, which the accounts book as a liability of the banking sector and the issuer side does not pick
  up. The test meant to catch this (`test_what_is_held_equals_what_is_owed_for_every_instrument`) passes anyway, so
  the test needs looking at as well as the view.
- **Unverified claim**: that TIC Table 2 attributes securities to the country of the issuer. To be confirmed from the
  TIC form instructions.
- The Fed's download packages used for H.15 and H.4.1 are due to be retired on 2027-03-31.

## Not built for the euro area yet

System map, ranking of unusual flows, share of GDP, interest rates, ECB announcements, a weekly central bank view, and
a common currency for comparing the two economies. Its overview is three tiles and two tables. The download already
holds who-holds-whose-paper detail from 2013:Q4 (deposits, debt securities, loans, listed shares, fund shares), unused.

## Next

1. Fix the fund-shares gap and the test that missed it.
2. Finish the euro-area overview: system map and unusual flows, then who-holds-whose-paper, then a common currency.
3. Links between economies: BIS international banking statistics and the IMF's portfolio survey.
4. Japan. Only the Bank of Japan's download page has been checked, not the file format.
