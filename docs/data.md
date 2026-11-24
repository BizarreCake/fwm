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
  - Member countries: the same dataset has them; only the euro-area aggregate is loaded.
- [x] **Euro area overview** — the system map and the latest quarter's unusual flows, largest flows and valuation changes, built the same way as for the US. Central banks and other banks are ranked separately. (`systemmap.py`, `overview.py`)
- [x] **Who holds whose paper, euro area** — a holder-by-issuer matrix per quarter for debt securities, loans, deposits, listed shares and fund shares, from the ECB's counterpart-sector series. Positions with the rest of the world are computed as the remainder. Debt securities, listed shares and fund shares start in 2013:Q4; loans and deposits in 1999. On the instrument pages, with an assistant tool. The US accounts have nothing like it. (`euroarea.who_to_whom`)
- [x] **Euro area rates, GDP and exchange rate** — ECB deposit facility rate (daily from 1999), the ECB's AAA government yield curve at 3 months, 2 and 10 years (daily from September 2004), nominal GDP (quarterly from 1995, not seasonally adjusted), and the ECB's dollar reference rate (daily from 1999). (`eacontext.py`)
- [x] **ECB announcements** — 16 hand-picked events since 2008, each read from its ECB press release. (`events_ea.csv`)
- [x] **Eurosystem balance sheet, weekly (ECB weekly financial statement, dataset ILM)** — every Friday since January 1999, in euro: securities (those held for monetary policy separately), lending to banks, gold, banknotes, banks' deposits, government deposits, capital. Same page and tools as the weekly Fed data. (`euweekly.py`)
- [x] **Economies side by side** — amounts outstanding by instrument and holdings by sector group for the US and the euro area, in dollars at the quarter-end ECB reference rate and as a share of each economy's GDP, from 1999. Rows are matched as closely as the two sets of accounts allow; the differences are stated on the card. This is the only place euro amounts are converted. (`compare.py`)
- [x] **Links between economies (IMF portfolio positions by counterpart economy, formerly CPIS; BIS locational banking statistics)** — in US dollars, for the United States, euro area, Japan, United Kingdom, China and Cayman Islands, with everywhere else as a remainder. Holdings of each other's equity and fund shares and debt securities at the end of June and December (annual before 2013), 2001 to 2025; claims and liabilities of banks located in each economy towards residents of the others, quarterly from 1999; and all reporting banks' positions with each economy split into dollars and euro. Page `#/links`, one assistant tool. (`links.py`, `uv run fwm ingest --only links`, about four minutes, 180 MB of downloads)
  - The euro area is the sum of 21 members with positions between members removed, at today's membership for every date. Croatia does not report portfolio holdings; eight small members do not report bank positions.
  - A period is left empty when the members reporting in it stand for under 90% of the usual total, so a missing reporter is not drawn as a fall.
  - China and the Cayman Islands publish bank positions in total only. The currency of bank positions is published only for all reporting banks together, not by pair.
  - Securities are placed by the issuer's residence and bank positions by the office's location, so holdings through financial centres show as claims on the centre.
  - Not included: direct investment, lending by non-banks, derivatives, and reserves by country. No sectors, maturities or flows, though both sources have some of this. No vintages kept.
  - Checked against TIC at end-2025: US holdings abroad agree exactly (same underlying survey), and Japanese and euro-area holdings of US equities agree within 3%. Their holdings of US debt are about 30% lower than TIC, mainly because the portfolio survey leaves out reserves. UK lower and Cayman higher than TIC, from custody against ownership.
  - Only the countries inside those six economies are stored as reporters; other countries are in the downloads but not loaded.
- [x] **Every country in the cross-border data** — the same two sources, now kept for every reporting country (about 90 in the IMF survey, about 30 publishing bank positions by country). Each country page has a card for its positions with every other country: what it reports by counterpart, and what the others report about it, for the four kinds, with totals over time. The assistant's tool takes any country alone or in a pair. (`links.country`, `links.pair`, `country_codes.csv`, `/api/countries/{id}/links`)
  - Country codes differ between the sources (two letters at the BIS, three at the IMF); `country_codes.csv` maps 249 countries, built by matching names and corrected by hand.
  - What others report about a country is a sum over the reporting countries only, and leaves out reserves, so it understates. Fewer countries report in June than in December; a date is left out when the reporters present stand for under 90% of the usual total.
  - Debt securities are all issuers together: a country's government bonds cannot be separated from its bank and company bonds.
  - Only countries in the US Treasury country list have pages (231); the United States itself has none, and is on the links page instead.
- [x] **Japan's financial accounts (Bank of Japan Flow of Funds, 2008 SNA basis)** — quarterly, 1997:Q4 onward, in yen. The third full economy: balance sheets for 14 sectors plus the rest of the world, and holders and issuers of nine instruments including government bonds and Treasury bills on their own, on the same pages as the others (`#/jp`). Stocks, flows and the Bank's reconciliation give the same three measures as elsewhere. One 6 MB download, loaded in about 15 seconds; each file is kept as a vintage. (`boj.py`, `japan.py`, `uv run fwm ingest --only boj`)
  - The Bank of Japan and the rest of the world are sectors of their own for the whole history; nothing is derived.
  - The series change statistical basis at 2005:Q1. Levels step there by more than flows and reconciliation explain (about ¥1,000T summed over all positions). Left as published and noted on the pages; it is the only such quarter.
  - Total liabilities are the sum of the lines, because the published total includes net worth.
  - Three holdings are negative at times and are real: securities dealers' short positions in government bonds and in foreign securities, and over-funded pension funds' claims on sponsors.
  - Residents' holdings of foreign securities are one item, not split into debt and equity.
  - No holdings by counterpart sector, and no weekly Bank of Japan balance sheet (the Bank publishes one every ten days; not loaded).
- [x] **Japan: rates, GDP, exchange rate, announcements** — policy rate (BIS central bank policy rates, daily), 2- and 10-year government bond yields (Ministry of Finance, daily), nominal GDP (OECD quarterly national accounts, seasonally adjusted, from 1994), yen per euro (ECB), with dollars per yen as the ratio of two ECB rates. 13 Bank of Japan announcements from 2010, each checked against the Bank's list of releases for its date and title; their details go no further than the title and the recorded policy rate. (`jpcontext.py`, `events_jp.csv`)
- [x] **Three economies side by side** — the comparison card and tool now include Japan.
- [x] **Z.1 vintages** — every release we download is kept in `data/raw/z1/vintages/`. Only one so far.

## Next

The aim is to explain how money moves between economies, not only inside the US. Economies are chosen by financial weight (US, euro area, Japan, UK, China), and the links between them come first.

1. [ ] **More from the cross-border sources** — holder sectors and maturities from the portfolio survey, the BIS consolidated statistics (banks by nationality rather than location), and direct investment positions (IMF, dataset DIP).
2. [ ] **The UK, then China** — the UK's quarterly financial accounts (ONS; not examined); China's data is thought to be annual and coarse, to be verified before committing.
3. [ ] **Bank balance sheets, weekly (H.8)** — loans, deposits, securities, cash. Can reuse the weekly tables, page layout and download reader built for H.4.1 (`ddp.py`).
4. [ ] **Weekly and monthly figures on the quarterly pages** — the weekly Fed data and monthly country data live on their own pages. The Fed's securities are at face value weekly and at market value in Z.1, so they cannot share a chart without care.

Smaller things left open on the euro area: member countries (the same ECB datasets have them); holdings by country, which have no euro-area equivalent of TIC loaded; history of the side-by-side comparison as a chart rather than one quarter; and ECB data vintages for the weekly and context series, which are overwritten on each download.

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
