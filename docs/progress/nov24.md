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

- **Unverified claim**: that TIC Table 2 attributes securities to the country of the issuer. To be confirmed from the
  TIC form instructions.
- The Fed's download packages used for H.15 and H.4.1 are due to be retired on 2027-03-31.

## Later the same day: the euro area finished

- **Correction.** An earlier version of this note said euro-area fund shares did not balance (€25.2T held against
  €23.1T owed). That was a stale figure from before the banking sector was merged; holders and issuers match, as the
  test says.
- **Overview.** The euro area has the same front page as the US: system map, unusual flows, largest flows and
  valuation changes.
- **Who holds whose paper.** A holder-by-issuer matrix for debt securities, loans, deposits, listed shares and fund
  shares, on the instrument pages and as an assistant tool. For example banks and central banks hold €4.72T of
  euro-area government debt securities and the rest of the world €3.04T (2026:Q2).
- **Rates, GDP, announcements.** ECB deposit rate, AAA government yields, GDP, and 16 ECB announcements, each read
  from its press release. Share of GDP now works on euro-area charts.
- **Eurosystem, weekly.** Every Friday from 1999 to 2026-11-20, on the same page and tools as the weekly Fed data.
- **Side by side.** The two economies compared by instrument and by holder, as a share of own GDP or in dollars.
- Checks after this: 154 tests pass, 2 skipped as before. Full benchmark, live: 44 of 45. The miss is
  `fed-largest-asset`: the assistant answered from the weekly Fed data (Treasuries 68% of assets) where the grader
  expects the quarterly accounts (69.9%). The answer is defensible; the question or the grader should say which.

Still open for the euro area: member countries, holdings by country, and vintages for the weekly and context series.

## Next

1. Links between economies: BIS international banking statistics and the IMF's portfolio survey.
2. Japan. Only the Bank of Japan's download page has been checked, not the file format.
