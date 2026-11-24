# Global Financial Intelligence System — Design Summary

**Status:** Initial design / iterative MVP  
**Goal:** Build an interactive, progressively expanding representation of the global financial system that an AI agent can explore to explain financial and economic developments with traceable evidence. **Prediction is a later phase**, not a prerequisite.

## 1. Product vision

Create an analytical environment combining:

1. **An explorable financial graph** showing institutions, economic sectors, assets, liabilities, transactions, and relationships over time.
2. **A conversational research agent** that answers questions by traversing the graph, querying numerical data, examining events, and testing alternative explanations.
3. **Incrementally added financial subsystems** that expand the system's coverage without rebuilding what already works.

Example questions:

- Who is financing the US government, and how has that changed?
- Why are Treasury yields rising? What evidence supports competing explanations?
- How do changes in bank lending affect government debt markets and households?
- Where is cross-border capital moving, and which institutions are exposed?
- What are the most unusual changes in financial conditions this month?

**Guiding principle:** Build a *financial investigator*, not just a chatbot over news or a dashboard of unrelated market charts. Every explanation should be inspectable, quantitative where possible, and linked to its sources.

## 2. What is a "piece" of the world?

Organize development around **connected financial subsystems**, not merely asset classes or countries.

A subsystem is a coherent domain with:

- Entities and economic sectors involved.
- Instruments, assets, liabilities, and relationships.
- Historical positions, transactions, and relevant observations.
- Data sources and update frequency.
- Analytical tools and questions it makes answerable.
- Visualizations and explicit data-coverage limitations.

For instance, **US Government Financing** includes Treasury issuance, debt ownership, yields, and financing relationships. **Commercial Banking** adds deposits, lending, securities holdings, and monetary interactions. Their overlap enables new cross-subsystem explanations.

**Prioritize subsystems that connect to existing ones and unlock new useful questions.** Avoid building isolated islands of data.

## 3. Architecture: one common model, many graph views

Do **not** maintain independent, incompatible graphs for stocks, bonds, banking, and real estate.

Build a shared, typed financial data model. Specialized subsystems contribute information to it; the UI generates context-specific *projections*.

### Core concepts

| Concept | Meaning |
| --- | --- |
| Entity / sector | Institution, government, household sector, bank sector, fund, country |
| Instrument | Deposit, loan, government bond, equity, mortgage, swap, etc. |
| Position | Who holds a claim on whom, through what instrument, at a given time |
| Transaction | Actual exchange, issuance, lending, repayment, or transfer during a period |
| Observation | Measured variable, e.g. interest rate, issuance, credit spread |
| Event | Policy decision, economic release, corporate or geopolitical development |
| Hypothesis | Possible causal explanation, explicitly distinct from an observed fact |

A relationship needs more than `source → target`: include the **holder, issuer/counterparty, instrument, value, currency, date, and provenance** where applicable. Use separate typed representations for positions, transactions, observations, and inferred hypotheses.

### Four complementary graph views

1. **Ownership/liability graph:** Who owns what? Who owes whom?
2. **Transaction/financing graph:** Who is providing new financing to whom, through which transactions?
3. **Risk/funding graph:** Who bears market or credit risk? Where are leverage, collateral, hedges, and short-term funding dependencies?
4. **Events/mechanisms graph:** What policy changes, economic events, and *hypothesized* causal pathways may explain developments?

These are different projections over related information, **not interchangeable edge types**. Hypothesized causal links must not be presented as established facts.

### Essential accounting distinctions

- **Stock ≠ flow ≠ valuation change.** An increase in market capitalization does not mean an equal amount of money entered the market.
- **Money creation ≠ transfer of existing money.** Bank credit and central-bank operations differ fundamentally from secondary-market asset purchases.
- **Ownership ≠ economic risk exposure.** Derivatives, hedging, and leverage can relocate risk without equivalent outright asset purchases.
- **Observed bilateral data ≠ estimated bilateral data.** Some datasets impute counterparty relationships from aggregates.
- **Balance-sheet growth ≠ net new investment.** Reconcile transactions, price changes, currency changes, write-offs, and reclassifications.

The accounting framework should draw on established institutional-sector and financial-instrument classifications (e.g., SNA / official financial accounts).

## 4. Incremental subsystem roadmap

| Stage | Subsystem | New explanatory capability |
| --- | --- | --- |
| **0** | Shared financial model + graph explorer | Consistent concepts, time, provenance, relationships, and visual navigation |
| **1** | US government financing | Debt issuance, yields, maturity, creditors, debt ownership |
| **2** | Banking + monetary system | Deposits, bank credit, reserves, central-bank operations, liquidity |
| **3** | Institutional investors | Pension funds, insurers, money-market funds, investment-fund allocations |
| **4** | International finance | Cross-border bank claims, portfolio holdings, currencies, capital flows |
| **5** | Corporate finance + equities | Business lending, bond issuance, shares, buybacks, corporate funding |
| **6** | Households + real estate | Mortgages, savings, household debt, housing and property finance |
| **7** | Derivatives + leveraged finance | Futures, options, swaps, repo, margin, collateral, risk transfer |
| **8** | Real economy + trade | Production, spending, income, trade, commodities, physical flows |

**This order is flexible.** Introduce lightweight supporting indicators (e.g., repo rates, news, inflation, economic releases) as soon as earlier subsystems need them, even before a full domain integration exists.

### How to choose the next subsystem

Evaluate candidates by:

- **Connectivity:** How many existing relationships or domains will become more useful?
- **Question unlock:** Which important unanswered questions become answerable?
- **Data quality/availability:** Are sources reliable, historical, maintained, and sufficiently timely?
- **Engineering cost:** How hard will ingestion, reconciliation, tooling, and maintenance be?

A conceptual ranking objective is:

`priority ≈ expected gain in useful answerable questions / integration-and-maintenance cost`

The agent should record unanswered questions and identify missing data/capabilities, creating an evidence-based expansion backlog.

## 5. UI and user interaction

**Primary layout:** Interactive graph explorer + chatbot + linked charts / evidence panel.

### Core interactions

- Select an entity or sector to inspect assets, liabilities, counterparties, instruments, and changes over time.
- Click a relationship to see magnitude, historical chart, definition, source, last update, and uncertainty.
- Switch between **exposure**, **transaction**, and **risk** views.
- Filter by date, geography, sector, instrument, currency, and confidence/coverage.
- Ask a question; have the agent construct and highlight only the **relevant subgraph**, not display an unreadable global hairball.
- Click a claim in the agent's answer to inspect the exact data or calculation supporting it.
- Select nodes/edges to change the chatbot's conversational context; have agent responses highlight relevant nodes, edges, and time periods.
- Use **historical replay** to examine the system as known on a past date, respecting publication lags and data vintages.

### Visibility into incompleteness

Represent coverage explicitly:

- **Observed:** Directly sourced and measured.
- **Estimated:** Derived/imputed with stated methodology.
- **Known but unmeasured:** Relevant relationship, inadequate quantitative evidence.
- **Not implemented:** Domain or analytical capability not yet integrated.

Never let the agent silently substitute assumed institution-level facts for sector-level aggregates.

## 6. Agent design: structured financial investigations

The LLM coordinates investigations. **Data systems calculate; the agent interprets.** Do not rely on RAG alone.

### Investigation workflow

1. **Define the question and time horizon.** Identify the observed change that requires explanation.
2. **Retrieve measurements.** Examine levels, differences, composition, and history.
3. **Traverse relevant relationships.** Find connected sectors, holders, issuers, and funding channels.
4. **Form competing hypotheses.** E.g., issuance changes, rate expectations, allocation shifts, funding stress.
5. **Gather discriminating evidence.** Pull additional time series, positions, transactions, derivatives, and events.
6. **Check accounting consistency and contradictions.** Distinguish measured flows from market-price effects.
7. **Explain with uncertainty.** Separate facts, plausible mechanisms, alternatives, unknowns, and source links.
8. **Make the investigation interactive.** Render highlighted graph paths, charts, and drill-down evidence.

### Example analytical tools

```python
get_balance_sheet(entity_or_sector, date)
get_counterparty_exposures(holder_or_issuer, instrument, date)
get_transactions(source, destination, instrument, start, end)
compare_periods(metric, start, end)
decompose_position_change(entity, instrument, period)
trace_financial_network(entity, relation_types, depth)
find_significant_changes(scope, period)
get_related_events(entity_or_topic, start, end)
get_source_metadata(observation_id)
```

Return **structured results with units, observation dates, publication dates, coverage, and provenance**. Tool names and exact APIs are provisional.

### A good answer should include

- What changed, quantitatively and when.
- Which financial relationships matter.
- Evidence supporting a proposed mechanism.
- Evidence contradicting or failing to establish it.
- Alternative plausible explanations.
- What is still unknown or unavailable.
- Direct links to underlying observations and source documents.

**Guardrail:** The system must not turn correlations or news narratives into unsupported causal claims.

## 7. Technical architecture

```text
Official financial accounts   Market/time-series data   News/events/documents
          |                            |                         |
          +----------------------------+-------------------------+
                                       |
                    Ingestion, normalization, entity resolution,
                    accounting checks, vintages, provenance
                                       |
            +--------------------------+--------------------------+
            |                          |                          |
     Financial relationship DB     Time-series store        Document store
            |                          |                          |
            +--------------------------+--------------------------+
                                       |
                        Typed analytical tools / APIs
                                       |
                          Investigation agent (LLM)
                                       |
                   Graph explorer + charts + chat + citations
```

**Pragmatic initial stack:**

- **PostgreSQL:** entities, relationships, positions/transactions metadata, provenance, subsystem registry.
- **Parquet + DuckDB (or a time-series-optimized store):** bulk historical observations and analytics.
- **Document retrieval:** official releases, methodology notes, news and relevant events.
- **Graph UI:** filtered, dynamic subgraphs generated from the common model.
- **Optional later Neo4j/graph database:** add only if graph queries justify it.

Do not encode every numerical observation as an individual graph edge. Store dense time series in an appropriate analytical store and join them into graph views as needed.

### Subsystem integration contract

Every subsystem should register:

```yaml
id: us_government_financing
requires: [core_financial_model]
entities: [us_treasury, federal_reserve, us_government_sector]
instruments: [treasury_bills, treasury_notes, treasury_bonds]
data_sources: [us_treasury, fed_z1, fed_from_whom_to_whom]
capabilities: [get_debt_issuance, get_debt_holders, get_yield_curve]
questions:
  - Who holds US government debt?
  - How has its financing changed over time?
visualizations: [issuer_holder_graph, debt_composition, ownership_history]
```

Integrations should map to shared identifiers and classifications, declare their limitations, and remain independently replaceable.

## 8. Data sources to prioritize

| Source | Initial use |
| --- | --- |
| **Federal Reserve Z.1** | US sector financial accounts: holdings, liabilities, transactions |
| **Federal Reserve From-Whom-to-Whom** | Estimated US issuer–holder positions by sector and instrument |
| **US Treasury** | Debt issuance, outstanding debt, maturity, financing activity |
| **FRED / ALFRED** | Rates, credit, macro indicators, and historical data vintages |
| **BIS** | Cross-border banking, debt, derivatives, credit, property statistics |
| **IMF** | Balance of payments, international portfolio positions, financial statistics |
| **OECD** | Cross-country financial accounts and balance sheets |
| **CFTC** | Aggregate futures/options positioning by participant category |
| **ICI** | Fund and ETF flows / net issuance |
| **News and official releases** | Events, policy changes, narrative context and corroboration |

Start with a handful of US sources; expand internationally after domestic reconciliation and agent tooling work. Note that comprehensive transaction-level counterparty data is **not publicly observable**. Many aggregate datasets are lagged or estimated.

## 9. First MVP: one coherent financial loop

**Scope:** US Treasury, Federal Reserve, commercial banks, households, and money-market funds.

Focus on the connections among:

- Government debt issuance and outstanding stock.
- Sector-level holdings of Treasury securities.
- Deposits, bank credit, reserves, and central-bank operations.
- Households' deposits and money-market fund holdings.
- Basic rates and financing conditions.

**Deliverables:**

1. Versioned schema for entities, instruments, positions, transactions, and observations.
2. Ingestion of the initial official financial-accounting datasets with provenance and time handling.
3. Interactive graph with clickable edges and historical charts.
4. Tool-using chatbot able to answer **~20 predefined questions** with numerical evidence and citations.
5. Coverage / uncertainty indicators and an explicit "cannot answer with available data" outcome.
6. A backlog of unanswered cross-domain questions to guide the next module.

**Example MVP questions:**

- Who holds US Treasury securities at the sector level?
- Which sectors increased Treasury holdings between two quarters?
- How much of a change in outstanding holdings was transaction-related versus valuation-related, where decomposition is supported?
- How are bank holdings of government securities related to other parts of bank balance sheets?
- What happens to the system's explanation when a requested breakdown is not available?

## 10. Quality, evaluation, and risks

### Evaluate before expanding

Use a versioned benchmark of historical financial questions and scenarios. Score:

- Correct numbers, units, definitions, and accounting.
- Relevant relationship retrieval and coherent multi-hop investigations.
- Proper treatment of lagged and revised data; no look-ahead bias.
- Clear distinction among observation, estimation, correlation, and causality.
- Consideration of alternative explanations and contradictory evidence.
- Citation quality, uncertainty calibration, and appropriate refusal to speculate.
- New questions answered after each additional subsystem (measured capability gain).

### Major risks

- Disparate sector/country/instrument definitions and double-counted exposures.
- Incorrect inference of flows from changing holdings or prices.
- Missing bilateral counterparty data and opaque private markets.
- Publication lags, revisions, and nonuniform historical coverage.
- Spurious causal narratives generated from coincident time series.
- Graph complexity making the UI harder to understand rather than easier.

Mitigate these with typed accounting records, explicit source and vintage metadata, reconciliation tests, visible uncertainty, scoped graph views, and adversarial agent evaluations.

## 11. Development loop

For each next subsystem:

1. Define the **questions it should unlock**.
2. Identify minimum required entities, instruments, and relationships.
3. Validate data availability, definitions, quality, and update frequency.
4. Map the data into the shared financial model with accounting checks.
5. Add analytical tools and visual graph projections.
6. Test questions and evidence quality against a benchmark.
7. Measure cross-subsystem capability gains and log remaining knowledge gaps.
8. Select the next subsystem by expected benefit and cost.

**Long-term trajectory:**

**Financial explorer → Evidence-based financial investigator → Scenario/risk analysis → Optional predictive financial world model.**

The near-term target is the **investigator**. A small, reliable, expandable system that can justify its answers is more valuable than a vast graph that produces convincing but unverifiable stories.
