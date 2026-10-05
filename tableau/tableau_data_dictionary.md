# Tableau Data Dictionary

Columns of the four CSV files in `data/processed/tableau/`, exported from the PostgreSQL views in
`sql/analytical_views.sql` and `sql/data_quality.sql`.

Conventions:
- **Flags** (`is_*`, `in_trend_window`, `has_invalid_dates`, `small_sample`) are `1` / `0`, so `SUM()` counts them.
  An empty flag means "not applicable" (e.g. `is_late` for an order that was not delivered).
- **Empty fields are NULL** (unknown or not applicable), never zero.
- **Money** is in Brazilian reais (R$). **Days** are decimal days.
- **Revenue** = item price + freight, for orders not `canceled` or `unavailable`.
- **Late** = delivered after the estimated delivery date (same day = on time).

---

## sales_dashboard.csv

One row per order item. Orders without items (775) appear once with empty item fields.

| Column | Type | Description | Business meaning |
|---|---|---|---|
| order_id | String | Order identifier | Use `COUNTD` for order counts |
| order_item_id | Whole number | Item sequence within the order (1, 2, …) | Empty for orders without items |
| customer_unique_id | String | Identifies the person across orders | Use `COUNTD` for customers |
| customer_state | String | 2-letter state code of the delivery address | Region filter |
| state_name | String (State/Province) | Full state name | Map field |
| macro_region | String | IBGE macro-region (North, Northeast, Center-West, Southeast, South) | Higher-level region |
| order_status | String | Current order status | Status filter |
| order_purchase_date | Date | Date the order was placed | Date filter |
| order_month | Date | First day of the purchase month | Monthly trends |
| in_trend_window | Flag | 1 if purchased Jan 2017 – Aug 2018 | Filter for trend charts |
| is_revenue_order | Flag | 1 if status is not canceled/unavailable | Revenue population |
| product_category | String | English product category; `unknown` = category missing in source | Category filter / charts |
| price | Decimal | Item price | Product revenue |
| freight_value | Decimal | Freight charged for the item | Shipping cost |
| item_value | Decimal | price + freight_value | Value regardless of status |
| revenue | Decimal | item_value for revenue orders, else empty | Sum for Total Revenue |

## operations_dashboard.csv

One row per order.

| Column | Type | Description | Business meaning |
|---|---|---|---|
| order_id | String | Order identifier | `COUNT` for orders |
| customer_unique_id | String | Person identifier | Customer counts |
| customer_state, state_name, macro_region | String | Delivery location (see above) | Region analysis |
| order_status | String | Current order status | Status distribution |
| order_purchase_date | Date | Purchase date | Date filter |
| order_month | Date | Purchase month | Trends |
| in_trend_window | Flag | 1 if Jan 2017 – Aug 2018 | Trend filter |
| primary_category | String | Category holding most of the order's value | Category filter; each order counted once |
| item_count | Whole number | Items in the order (0 = no items) | Order size |
| freight_value | Decimal | Total freight of the order | Freight cost per order |
| revenue | Decimal | Order revenue (empty for canceled/unavailable) | Revenue at risk from late delivery |
| is_revenue_order | Flag | 1 if not canceled/unavailable | Freight / revenue population |
| is_canceled | Flag | 1 if status = canceled | Cancellation rate |
| is_unavailable | Flag | 1 if status = unavailable (seller could not fulfil) | Fulfilment failures |
| is_measurable_delivery | Flag | 1 if delivered, has a delivery date and dates are consistent | Denominator for delivery metrics |
| is_late | Flag | 1 late, 0 on time, empty if not measurable | Numerator for Late Delivery % |
| delivery_outcome | String | `Late` / `On time` / empty | Colour for delivery charts |
| timeliness_bucket | String | Delivery date vs estimate, 7 ordered buckets | Actual vs estimated chart |
| delivery_days | Decimal | Purchase → delivery to customer | Average delivery time |
| estimated_days | Decimal | Purchase → estimated delivery date | Promised delivery time |
| days_vs_estimate | Whole number | Delivery date − estimated date (negative = early) | Size of the miss |
| approval_hours | Decimal | Purchase → payment approval | Approval speed |
| seller_handoff_days | Decimal | Approval → handed to carrier | Seller preparation time |
| carrier_transit_days | Decimal | Handed to carrier → delivered | Carrier transit time |
| has_invalid_dates | Flag | 1 if lifecycle dates are out of order | Excluded from time metrics |

## regional_dashboard.csv

One row per state, all-time totals.

| Column | Type | Description | Business meaning |
|---|---|---|---|
| customer_state, state_name, macro_region | String | State identifiers | Map / labels |
| revenue | Decimal | State revenue | Revenue contribution |
| revenue_share_pct | Decimal | % of national revenue | Contribution |
| revenue_rank | Whole number | 1 = highest revenue | Sorting |
| revenue_orders | Whole number | Orders that generated revenue | Volume |
| customers | Whole number | Distinct customers | Customer base |
| avg_order_value | Decimal | Revenue / revenue orders | Basket size |
| avg_freight_per_order | Decimal | Average freight per revenue order | Shipping cost to the region |
| delivered_orders | Whole number | Orders with a measurable delivery | Sample size for rates |
| late_orders | Whole number | Late deliveries | Volume of late orders |
| late_pct | Decimal | Late orders / delivered orders × 100 | Delivery reliability |
| national_late_pct | Decimal | National late % (6.78) | Reference line |
| late_pct_vs_national_pp | Decimal | late_pct − national, in percentage points | Gap to national |
| avg_delivery_days | Decimal | Average delivery time | Speed |
| national_avg_delivery_days | Decimal | National average (12.57) | Reference line |
| late_order_revenue | Decimal | Revenue of orders delivered late | Revenue exposed to late delivery |
| revenue_tier | String | `Higher revenue` if revenue ≥ median state revenue | Segment axis |
| delivery_tier | String | `Late rate above national` / `Late rate at/below national` | Segment axis |
| segment | String | revenue_tier / delivery_tier combined | Scatter colour |
| small_sample | Flag | 1 if fewer than 100 delivered orders (RR, AP, AC) | Treat rates with caution |

## data_quality_summary.csv

One row per data-quality check, measured in PostgreSQL.

| Column | Type | Description | Business meaning |
|---|---|---|---|
| check_category | String | Missing values, Duplicate records, Invalid values, Invalid dates, Orphan records, Unmatched foreign keys, Inconsistent categories | Grouping |
| table_name | String | Table checked | Where the issue is |
| check_name | String | Rule description | What was checked |
| severity | String | `critical`, `warning`, `info` | Impact if violated |
| record_count | Whole number | Records violating the rule | Size of the issue |
| total_records | Whole number | Rows in the table | Denominator |
| pct_of_records | Decimal | record_count / total_records × 100 | Relative size |
| status | String | PASS (0 records), FAIL (critical), WARNING, INFO (expected by design) | Traffic-light status |
