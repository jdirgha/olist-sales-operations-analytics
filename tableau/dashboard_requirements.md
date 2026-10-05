# Tableau Public Dashboard Requirements & Build Guide

Three dashboards for sales, operations and leadership stakeholders, built in **Tableau Public**
(free desktop app) from CSV exports of the PostgreSQL analytical views.

Why CSV: Tableau Public cannot connect to a local PostgreSQL database. The pipeline exports the
views to `data/processed/tableau/`; after a pipeline run, refresh the data sources in Tableau and
republish.

```bash
python -m src.transformation --views --export
```

| File | Grain | Rows | Used by |
|---|---|---|---|
| `sales_dashboard.csv` | order item (+ 1 row per order without items) | 113,425 | Dashboard 1 |
| `operations_dashboard.csv` | order | 99,441 | Dashboard 2 |
| `regional_dashboard.csv` | state | 27 | Dashboard 3, section 1 |
| `data_quality_summary.csv` | data-quality check | 36 | Dashboard 3, section 2 |

Column definitions: [`tableau_data_dictionary.md`](tableau_data_dictionary.md).

---

## 1. Setup

1. Install Tableau Public from <https://public.tableau.com/app/discover> (free account required to save).
2. **Connect → To a File → Text file** → `data/processed/tableau/sales_dashboard.csv`.
3. On the Data Source tab check the field types (click the type icon to change):
   - `order_purchase_date`, `order_month` → **Date**
   - `order_item_id`, `in_trend_window`, `is_*` flags → **Number (whole)**
   - `state_name` → **Geographic Role → State/Province**
4. Add the other files as separate data sources: **Data → New Data Source → Text file**.
   Repeat step 3 for each (`regional_dashboard.state_name` also gets the State/Province role).
5. First map you build: **Map → Edit Locations → Country/Region = Brazil** so state names resolve.

Validation after connecting: an unfiltered `SUM(revenue)` in `sales_dashboard` must be
**15,735,527.03**, and `COUNTD(order_id)` must be **99,441**. If not, a field type is wrong.

---

## 2. Calculated fields

Create these with **Analysis → Create Calculated Field** in the data source shown.

### sales_dashboard

| Name | Formula | Notes |
|---|---|---|
| Total Revenue | `SUM([revenue])` | `revenue` is already NULL for canceled/unavailable orders |
| Total Orders | `COUNTD([order_id])` | All orders placed |
| Revenue Orders | `COUNTD(IF NOT ISNULL([revenue]) THEN [order_id] END)` | Orders that generated revenue |
| Average Order Value | `[Total Revenue] / [Revenue Orders]` | Expected unfiltered: 160.24 |
| Total Customers | `COUNTD([customer_unique_id])` | People, not per-order customer ids |
| MoM Revenue % | `(SUM([revenue]) - LOOKUP(SUM([revenue]), -1)) / ABS(LOOKUP(SUM([revenue]), -1))` | Table calculation; compute using `order_month` |

### operations_dashboard

| Name | Formula | Notes |
|---|---|---|
| Orders | `COUNT([order_id])` | One row per order |
| Avg Delivery Days | `AVG([delivery_days])` | NULL for orders without a measurable delivery, so they are ignored |
| Avg Estimated Days | `AVG([estimated_days])` | Same population as delivery days |
| Late Delivery % | `SUM([is_late]) / SUM([is_measurable_delivery])` | Expected unfiltered: 6.78% |
| Cancellation % | `SUM([is_canceled]) / COUNT([order_id])` | Expected unfiltered: 0.63% |
| Avg Freight per Order | `AVG(IF [is_revenue_order] = 1 THEN [freight_value] END)` | Expected unfiltered: 22.82 |
| Delivered Orders | `SUM([is_measurable_delivery])` | Used to hide small categories |
| National Late % | `{FIXED : SUM([is_late])} / {FIXED : SUM([is_measurable_delivery])}` | Reference line; ignores dashboard filters |

### data_quality_summary

| Name | Formula |
|---|---|
| Checks Passed | `SUM(IF [status] = "PASS" THEN 1 ELSE 0 END)` |
| Warnings | `SUM(IF [status] = "WARNING" THEN 1 ELSE 0 END)` |
| Failed Checks | `SUM(IF [status] = "FAIL" THEN 1 ELSE 0 END)` |
| Missing Records | `SUM(IF [check_category] = "Missing values" AND [severity] <> "info" THEN [record_count] END)` |
| Duplicate Records | `SUM(IF [check_category] = "Duplicate records" THEN [record_count] END)` |
| Invalid Records | `SUM(IF [check_category] = "Invalid values" OR [check_category] = "Invalid dates" THEN [record_count] END)` |
| Validation Status | `IF [Failed Checks] > 0 THEN "FAILED" ELSE "PASSED" END` |

---

## 3. Design standards

- **Size:** Dashboard → Size → Fixed, 1200 × 850 (fits a laptop screen without scrolling).
- **Layout:** title row → KPI row → 2 × 2 chart grid (Dashboard 3: two sections). Filters in a right-hand column.
- **Colour:** one neutral blue (`#4E79A7`) for all standard marks. One accent orange (`#F28E2B`) only for
  late deliveries / above-national rates. Red (`#E15759`) only for FAIL. Grey for PASS/INFO context.
- **No** 3D, pie charts with many slices, gridline clutter, or decorative images.
- **Numbers:** revenue as `R$#,##0` (KPI cards `R$0.0M`), rates as `0.0%`, days as `0.0`.
- **Titles state the business question**, e.g. *"Is revenue growing?"*, with the metric in the subtitle.
- **Tooltips:** metric name, value, and the comparison that matters (e.g. state late % vs national).
- **Trend charts** use `in_trend_window = 1` (Jan 2017 – Aug 2018). Earlier/later months are too sparse
  for trends (see `sql/sales_analysis.sql`). Add a caption: *"Complete months Jan 2017 – Aug 2018."*

---

## 4. Dashboard 1 — Sales Performance Overview

**Audience:** Sales Manager, Business Leadership. **Data source:** `sales_dashboard`.

**Business questions:** Is revenue growing? Which categories drive revenue? Which regions drive revenue?

### KPI cards (one sheet each, Text mark, large font)
| Card | Measure | Unfiltered value |
|---|---|---|
| Total Revenue | `Total Revenue` | R$15.74M |
| Total Orders | `Total Orders` | 99,441 |
| Average Order Value | `Average Order Value` | R$160.24 |
| Total Customers | `Total Customers` | 96,096 |

### Charts
| # | Sheet | Build | Question answered |
|---|---|---|---|
| 1 | Monthly Revenue Trend | Columns: `MONTH(order_month)` (continuous). Rows: `Total Revenue`. Mark: Line. Filter `in_trend_window = 1`. Tooltip: revenue, `MoM Revenue %`. | Is revenue growing? |
| 2 | Monthly Order Volume | Columns: `MONTH(order_month)`. Rows: `Total Orders`. Mark: Bar. Filter `in_trend_window = 1`. | Is demand growing, or only order value? |
| 3 | Revenue by Product Category | Mark: Treemap. Size and label: `Total Revenue`; Detail: `product_category`. Exclude NULL category. Tooltip: revenue and % of total (quick table calc). | How concentrated is revenue across categories? |
| 4 | Top 10 Product Categories | Rows: `product_category`; Columns: `Total Revenue`; Mark: Bar, sorted descending. Filter `product_category` → Top 10 by `Total Revenue`. Labels on bars. | Which categories drive revenue? |
| 5 | Revenue by State | Filled map: `state_name` on Detail, `Total Revenue` on Colour (sequential blue). Tooltip: state, revenue, orders, AOV. | Which regions drive revenue? |

### Filters (show on dashboard, **Apply to Worksheets → All Using This Data Source**)
- `order_purchase_date` — range of dates
- `state_name` — multiple values dropdown
- `product_category` — multiple values dropdown
- `order_status` — multiple values dropdown

---

## 5. Dashboard 2 — Operations Performance

**Audience:** Operations Manager, Business Leadership. **Data source:** `operations_dashboard`.

**Business questions:** Are deliveries meeting expectations? Which regions have delivery problems? Are delays increasing?

### KPI cards
| Card | Measure | Unfiltered value |
|---|---|---|
| Average Delivery Time | `Avg Delivery Days` (format `0.0 "days"`) | 12.6 days |
| Late Delivery % | `Late Delivery %` | 6.8% |
| Cancellation % | `Cancellation %` | 0.6% |
| Average Freight Cost | `Avg Freight per Order` | R$22.82 |

### Charts
| # | Sheet | Build | Question answered |
|---|---|---|---|
| 1 | Actual vs Estimated Delivery | Columns: `timeliness_bucket` (exclude NULL, sorted by name). Rows: `Orders`. Mark: Bar. Colour: `delivery_outcome` (On time blue, Late orange). Label: percent of total. | Are deliveries meeting the promised date, and by how much? |
| 2 | Delivery Time Trend | Columns: `MONTH(order_month)`. Rows: `Avg Delivery Days` and `Avg Estimated Days` (Measure Values, one axis), and a second row `Late Delivery %` (line, orange). Filter `in_trend_window = 1`. | Are delays increasing? |
| 3 | Late Deliveries by State | Rows: `state_name` sorted by `Late Delivery %` desc. Columns: `Late Delivery %`. Mark: Bar. Reference line: `National Late %`. Colour: orange when above national (`[Late Delivery %] > [National Late %]`). Tooltip: delivered orders, late orders, avg days. | Which regions have delivery problems? |
| 4 | Late Deliveries by Category | Rows: `primary_category`; Columns: `Late Delivery %`, sorted desc. Filter `Delivered Orders` ≥ 100; Top 15. Same reference line and colour rule. | Which categories are most often late? |
| 5 | Order Status Distribution | Rows: `order_status` sorted by `Orders`; Columns: `Orders`. Mark: Bar. Label: count and percent of total. (`delivered` is ~97% — labels keep the small statuses readable.) | How many orders are stuck, canceled or unavailable? |

### Filters (Apply to All Using This Data Source)
- `order_purchase_date` — range of dates
- `state_name`
- `primary_category` (label it "Product Category")
- `order_status`

---

## 6. Dashboard 3 — Regional & Data Quality Analysis

**Audience:** Business Leadership, Operations Manager.
**Data sources:** `regional_dashboard` (section 1), `data_quality_summary` (section 2).
No filters: regional segments are defined on all-time totals.

**Business questions:** Which regions contribute most to revenue? Which regions experience
operational issues? How reliable is the underlying data?

### Section 1 — Regional performance
| # | Sheet | Build |
|---|---|---|
| 1 | State Scorecard (covers *Revenue by State*, *Orders by State*, *Late Delivery % by State*, *Average Delivery Time by State*) | Rows: `state_name`, sorted by `revenue` desc. Columns: `SUM(revenue)`, `SUM(revenue_orders)`, `SUM(late_pct)`, `SUM(avg_delivery_days)` — four bar panes sharing one state axis. Colour the late % and delivery-time panes by `delivery_tier` (above national = orange). Reference lines: `national_late_pct` and `national_avg_delivery_days`. Tooltip includes `small_sample`. |
| 2 | Revenue vs Late Rate (segments) | Scatter: Columns `SUM(revenue)` (log scale), Rows `SUM(late_pct)`, Detail `customer_state`, Label `customer_state`, Colour `segment`. Reference lines: median state revenue (Analytics → Median) and `national_late_pct`. |

The scatter shows the four segments as quadrants:
*Higher revenue / late rate above national* (e.g. RJ, BA, CE), *Higher revenue / late rate at/below national*
(e.g. SP, MG, PR), *Lower revenue / late rate above national* (e.g. AL, MA, SE),
*Lower revenue / late rate at/below national*.

### Section 2 — Data quality
| # | Sheet | Build |
|---|---|---|
| 3 | Data Quality KPIs | Text tiles: `Validation Status`, `Checks Passed`, `Warnings`, `Failed Checks`, `Missing Records`, `Duplicate Records`, `Invalid Records`. |
| 4 | Checks by Category | Rows: `check_category`; Columns: count of checks; Colour: `status` (PASS grey, INFO light grey, WARNING orange, FAIL red). Stacked bar. |
| 5 | Check Detail | Text table: `check_category`, `table_name`, `check_name`, `status`, `record_count`, `pct_of_records`. Filter out `status = PASS` with a toggle (show on dashboard) so reviewers see issues first. |

Caption: *"Data quality measured in PostgreSQL after validation. FAIL = critical, would stop the pipeline.
WARNING = known issue handled in analysis. INFO = expected by design. Details: docs/data_quality_report.md."*

---

## 7. Publish

1. **File → Save to Tableau Public As…**, sign in, name the workbook *Sales & Operations Analytics Dashboard*.
2. On the Tableau Public web page: add a description, turn on **Show Tabs** so the three dashboards
   appear as tabs, and copy the URL into the project README.
3. Refreshing: re-run the pipeline, open the workbook, **Data → Refresh** each data source,
   check the validation values in section 1, then save to Tableau Public again.

## 8. Acceptance checklist

- [ ] Unfiltered KPI values match the tables above (they come from the SQL analysis).
- [ ] Every chart title is a business question; every chart has a tooltip.
- [ ] Filters on Dashboards 1 and 2 apply to every sheet on that dashboard.
- [ ] Trend charts show Jan 2017 – Aug 2018 only, with a caption saying so.
- [ ] Orange is used only for late / above-national; red only for FAIL.
- [ ] Three dashboards appear as tabs on Tableau Public.
