# Business Requirements

## 1. Background

Olist is a Brazilian marketplace that connects small sellers to large online stores. It handles orders,
payments and delivery logistics on their behalf. Management has transaction data for ~100k orders,
but no single, trusted view of how sales are developing or how reliably orders are delivered.

## 2. Objective

Build a reproducible analytics pipeline and dashboards that let sales and operations stakeholders
answer the questions below from one validated data source, refreshed automatically.

## 3. Stakeholders

| Stakeholder | Needs |
|---|---|
| Sales / commercial leadership | Revenue trend, growth drivers, category and regional mix |
| Operations / logistics | Delivery speed, late deliveries, where and when fulfilment breaks down |
| Regional managers | How their state compares with the national picture |
| Data / BI team | Trustworthy, documented data with visible quality checks |

## 4. Business questions

**Sales**
1. How much revenue do we generate, and is it growing?
2. Is growth driven by more orders or by larger orders?
3. Which months, product categories and states drive revenue?
4. How concentrated is revenue across categories and regions?
5. Which categories are gaining or losing share?
6. What share of orders is canceled?

**Operations**
1. How long does delivery take, and how does it compare with the date promised to the customer?
2. What share of deliveries is late, and is it getting better or worse?
3. In which months, states and categories are late deliveries concentrated?
4. Which fulfilment stage (approval, seller hand-off or carrier transit) causes delays?
5. Do late orders cost more in freight?

**Regional**
1. Which states combine high revenue with poor delivery, so that improvement matters most?
2. How do macro-regions differ in order value, freight cost and delivery reliability?

**Data quality**
1. Can the numbers be trusted? What issues exist in the source data, and how were they handled?

## 5. KPI definitions

| KPI | Definition |
|---|---|
| Total revenue | Σ (item price + freight) for orders whose status is not `canceled` or `unavailable` |
| Total orders | Count of distinct orders, all statuses |
| Average order value (AOV) | Revenue ÷ orders that generated revenue |
| Customers | Distinct `customer_unique_id` (a person; Olist issues a new `customer_id` per order) |
| Revenue growth (MoM) | (Revenue this month − previous month) ÷ previous month |
| Cancellation rate | Canceled orders ÷ all orders |
| Average delivery time | Mean days from purchase to delivery, for measurable deliveries |
| Late delivery rate | Orders delivered after the estimated date ÷ measurable deliveries |
| Measurable delivery | Status `delivered`, has a delivery date, and lifecycle dates in a valid order |
| Average freight cost | Mean freight per item / per order |
| Revenue concentration | Share of revenue from the top 10 categories / top 3 states |

## 6. Scope

**In scope:** orders, order items, payments, customers, products and the category translation.
The period covered is September 2016 – October 2018. Trend analysis uses January 2017 – August 2018.

**Out of scope:** forecasting or machine learning, profitability (there is no cost data), seller-level
analysis, customer reviews and geolocation.

## 7. Deliverables

| Deliverable | Location |
|---|---|
| Automated pipeline (ingest → profile → clean → validate → load → analyse → export) | `src/`, `airflow/` |
| PostgreSQL model with constraints and indexes | `sql/schema.sql` |
| SQL analyses answering every question above | `sql/*_analysis.sql` |
| Analytical views for dashboards | `sql/analytical_views.sql`, `sql/data_quality.sql` |
| Tableau Public dashboards: Sales, Operations, Regional & Data Quality | `tableau/` |
| Data quality report | `docs/data_quality_report.md` |
| Business insights and recommendations | `docs/business_insights.md` |
| Automated tests | `tests/` |

## 8. Acceptance criteria

- Raw files are never modified, and every cleaning decision is logged and documented.
- A critical data-quality failure stops the pipeline before the database is loaded.
- Loaded row counts match the cleaned files, and the load is all-or-nothing.
- Dashboard KPIs reconcile exactly with the SQL analysis. This is checked by automated tests.
- The pipeline runs end to end both from the command line and from Airflow, with no hard-coded credentials.
