# Data: what we have, what we want, what's next

A working checklist. Update it when a source is added or a priority changes.
When a gap here is closed, also update the "What the data cannot say" section of the assistant's instructions in `src/fwm/agent.py`.

## In the system

- [x] **Fed Z.1 financial accounts** — quarterly, 1952:Q1 onward. Sector balance sheets, and holders and issuers of each instrument. (`z1.py`)
- [x] **Fed H.15 interest rates** — daily fed funds, 3-month, 2-year and 10-year Treasury yields. (`rates.py`)
- [x] **GDP** — nominal, from Z.1, as a four-quarter sum. (`context.py`)
- [x] **Fed announcements** — 23 hand-picked events since 2008, each checked against its press release. (`events.csv`)
- [x] **Fed balance sheet, weekly (H.4.1)** — every Wednesday since December 2002: securities held, loans, currency, bank reserves, reverse repos, the Treasury's cash account, capital. Has its own page and assistant tools. Federal Reserve only. (`fedweekly.py`)
- [x] **Foreign holders of US securities by country (Treasury TIC, SLT Tables 1 and 3)** — monthly from January 2020, about 60 to 77 countries: Treasuries (bills against bonds and notes), agency bonds, corporate bonds and equities (which include fund shares), each with official against private holders; net purchases and valuation from February 2023. One page per kind of security, and assistant tools. Every monthly file downloaded is kept in `data/raw/tic/vintages/`. (`tic.py`)
- [x] **US holdings of foreign securities by country (Treasury TIC, SLT Table 2)** — monthly from January 2020: foreign government bonds, corporate bonds and equities held by US residents. Shown on the country pages. (`tic.py`, `countries.py`)
- [x] **Countries as counterparties of the US** — one page per country (and the euro area and EU) with both directions. Not the country's own accounts. (`countries.py`)
- [x] **Euro area financial accounts (ECB quarterly sector accounts, dataset QSA)** — quarterly, 1999:Q1 onward, in euro. The second full economy: balance sheets for eight sectors plus the rest of the world, and holders and issuers of seven instruments, with the ECB's own transactions and other changes. Pages at `#/ea`, and the assistant's sector and instrument tools take `economy: "ea"`. Checked every quarter: sectors add up to the whole economy, lines to their parts, change = transactions + other changes, and holders = issuers once the rest of the world is included. Each release downloaded is kept in `data/raw/ecb/vintages/`. (`ecb.py`, `euroarea.py`) What it does not have yet:
  - Banks, central banks and money market funds are one sector, because that is the only split with history to 1999. Central banks (the Eurosystem) and other banks are separate from 2015 and shown as parts.
  - The rest of the world is read from residents' positions against non-residents, not published as a sector.
  - Derivatives are published net, so have no holders page. Fund shares issued by money market funds sit with banks.
  - No conversion to dollars, no GDP, interest rates, ECB announcements, weekly ECB balance sheet, system map or ranking of unusual flows. The euro-area overview is two tables.
  - Who-to-whom detail (which sector holds which sector's paper) is in the download for deposits, debt securities, loans, listed shares and fund shares from 2013:Q4, and is not used yet.
  - Member countries: the same dataset has them; only the euro-area aggregate is loaded.
- [x] **Z.1 vintages** — every release we download is kept in `data/raw/z1/vintages/`. Only one so far.

## Next

The aim is to explain how money moves between economies, not only inside the US. Economies are chosen by financial weight (US, euro area, Japan, UK, China), and the links between them come first.

1. [ ] **Finish the euro area** — an overview like the US one (system map, unusual flows), who-to-whom from the detail already downloaded, euro-area GDP and ECB policy rates, the Eurosystem's weekly statement, and a common currency for comparing economies (ECB reference exchange rates).
2. [ ] **Cross-border links between economies** — BIS international banking statistics (bank claims by country pair, including offshore dollars) and the IMF portfolio survey (securities holdings by country pair).
3. [ ] **Japan, then the UK, then China** — quarterly flow of funds for the first two (the Bank of Japan's download page responds; its file format has not been examined); China's data is thought to be annual and coarse, to be verified before committing.
4. [ ] **Bank balance sheets, weekly (H.8)** — loans, deposits, securities, cash. Can reuse the weekly tables, page layout and download reader built for H.4.1 (`ddp.py`).
5. [ ] **Weekly and monthly figures on the quarterly pages** — the weekly Fed data and monthly country data live on their own pages. The Fed's securities are at face value weekly and at market value in Z.1, so they cannot share a chart without care.

## Wanted, by the gap it closes

### Faster than quarterly
- [ ] Money market fund holdings, monthly (SEC and OFR) — includes who they lend to in repo.
- [ ] Treasury auctions and debt outstanding, daily — what was issued, at what maturity, to which bidder class.

### Below sector level
- [ ] Individual banks (regulatory call reports, quarterly).
- [ ] Individual funds and large investors (fund filings, 13F). Large and messy; wait for a specific need.

### Who lends to whom
- [ ] Repo market volumes and rates by segment (OFR, New York Fed).
- [ ] Estimated sector-to-sector links from Z.1 (holders assumed to own a proportional slice of each issuer). Derived, not observed; must be labelled as an estimate.

### Maturity, price and quality
- [ ] Treasury debt by maturity (Monthly Statement of the Public Debt).
- [ ] The Fed's portfolio by security (SOMA holdings).
- [ ] Market prices: equity indices, credit spreads, mortgage rates, the dollar.

### Context for "why"
- [ ] Events beyond the Fed: debt-ceiling episodes, Treasury refunding announcements, fiscal legislation, bank failures. Each needs a primary source.
- [ ] The full FOMC calendar, not only turning points.
- [ ] Macro data: inflation, unemployment, the federal deficit.

### History and revisions
- [ ] Backfill earlier Z.1 releases, to show how figures were revised.

### More of what we already ingest
- [ ] Non-financial assets (real estate, equipment), so net worth can be shown. In Z.1's balance-sheet tables, which are ingested but not displayed.
- [ ] Six Z.1 instruments without pages: F1, F2_4, F4_6, F519_1, F89_2, F89_3a. Includes trade credit and miscellaneous claims, which are also missing from the system map.

### Foreign holders, further back and in more detail
- [ ] Holdings by country before 2020. Older TIC files reach back to 2011 and earlier, but were later revised and do not line up with the current table.
- [ ] Who really owns what is held through custody centres (Belgium, Luxembourg, Ireland, Cayman Islands, UK). The annual TIC survey reallocates part of it.
- [ ] Foreign holdings that are not long-term securities or Treasury bills: bank deposits, loans, short-term paper, direct investment (other TIC forms and the BEA).
- [ ] Table 1's breakdown of foreign holdings by type of US issuer (banks, other financial, non-financial, asset-backed, fund shares). In the file, not ingested.
- [ ] Confirm from the TIC form instructions how Table 2 assigns a foreign security to a country (the country pages say: country of the issuer).
- [ ] What the unexplained monthly change in foreign bond holdings is (change in holdings less reported purchases and valuation; often tens of billions).

## Maintenance

- [ ] **Replace the H.15 and H.4.1 downloads before 2027-03-31.** The Fed is retiring the Data Download Program packages that `ddp.py` reads.
- [ ] **Keep H.4.1 vintages?** Only the latest download is kept. Weekly figures are rarely revised, so this is low priority.

## Rules for adding a source

- Keep the raw download and record which release it is.
- Add accounting checks that hold in every period, not only the latest.
- Label what is observed and what is derived or estimated.
- Hand-curated entries (events) cite a primary source that was actually read.
