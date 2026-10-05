# Data Dictionary

Tables in the PostgreSQL database `olist_analytics`, as defined in [`sql/schema.sql`](../sql/schema.sql).
Columns come from the Olist source CSVs after cleaning (`src/cleaning.py`).
The columns of the dashboard CSV exports are documented in
[`tableau/tableau_data_dictionary.md`](../tableau/tableau_data_dictionary.md).

Conventions: **NULL means unknown or not applicable, never zero.** Money is in Brazilian reais (R$).
Timestamps are Brazilian local time, without time zone.

## Source files

| Source file (`data/raw/`) | Table | Rows |
|---|---|---|
| `olist_customers_dataset.csv` | `customers` | 99,441 |
| `olist_orders_dataset.csv` | `orders` | 99,441 |
| `olist_order_items_dataset.csv` | `order_items` | 112,650 |
| `olist_order_payments_dataset.csv` | `payments` | 103,886 |
| `olist_products_dataset.csv` | `products` | 32,951 |
| `product_category_name_translation.csv` | merged into `products.product_category_name_english` | 71 |

Cleaning removed no rows. The geolocation, sellers and reviews files are part of the Kaggle download
but out of scope.

---

## customers

One row per customer record. Olist creates a new `customer_id` for every order, so use
`customer_unique_id` to count people.

| Column | Type | Null? | Description |
|---|---|---|---|
| customer_id | VARCHAR(32) | PK | Customer record for one order |
| customer_unique_id | VARCHAR(32) | No | Identifies the person across orders |
| customer_zip_code_prefix | CHAR(5) | No | First 5 digits of the postcode. Kept as text and left-padded with zeros |
| customer_city | VARCHAR(100) | No | City, trimmed and lowercased |
| customer_state | CHAR(2) | No | State code (e.g. `SP`), uppercased |

## orders

One row per order.

| Column | Type | Null? | Description |
|---|---|---|---|
| order_id | VARCHAR(32) | PK | Order identifier |
| customer_id | VARCHAR(32) | No | FK → `customers.customer_id` |
| order_status | VARCHAR(20) | No | `created`, `approved`, `invoiced`, `processing`, `shipped`, `delivered`, `canceled`, `unavailable` |
| order_purchase_timestamp | TIMESTAMP | No | When the order was placed |
| order_approved_at | TIMESTAMP | Yes | Payment approved. NULL = never approved |
| order_delivered_carrier_date | TIMESTAMP | Yes | Handed to the carrier. NULL = not shipped yet |
| order_delivered_customer_date | TIMESTAMP | Yes | Delivered to the customer. NULL = not delivered |
| order_estimated_delivery_date | TIMESTAMP | No | Delivery date promised at purchase (always midnight) |
| has_invalid_dates | BOOLEAN | No | Added in cleaning. TRUE if a lifecycle event is recorded before the event it must follow (189 orders). These are excluded from delivery-time metrics |

Constraints: delivery and estimated dates must be on or after the purchase date.

## order_items

One row per item line in an order.

| Column | Type | Null? | Description |
|---|---|---|---|
| order_id | VARCHAR(32) | PK, FK | FK → `orders.order_id` |
| order_item_id | SMALLINT | PK | Item sequence within the order (1, 2, …) |
| product_id | VARCHAR(32) | No | FK → `products.product_id` |
| seller_id | VARCHAR(32) | No | Seller who fulfilled the item |
| shipping_limit_date | TIMESTAMP | No | Deadline for the seller to hand the item to the carrier |
| price | NUMERIC(10,2) | No | Item price, ≥ 0 |
| freight_value | NUMERIC(10,2) | No | Freight charged for the item, ≥ 0 (0 = free shipping) |

## payments

One row per payment record of an order. An order can be paid in several parts, for example a voucher plus a card.

| Column | Type | Null? | Description |
|---|---|---|---|
| order_id | VARCHAR(32) | PK, FK | FK → `orders.order_id` |
| payment_sequential | SMALLINT | PK | Sequence of the payment within the order |
| payment_type | VARCHAR(20) | No | `credit_card`, `boleto`, `voucher`, `debit_card`, `not_defined` (3 rows) |
| payment_installments | SMALLINT | Yes | Number of installments, > 0. NULL where the source had an invalid 0 (2 rows) |
| payment_value | NUMERIC(10,2) | No | Amount paid, ≥ 0 |

## products

One row per product.

| Column | Type | Null? | Description |
|---|---|---|---|
| product_id | VARCHAR(32) | PK | Product identifier |
| product_category_name | VARCHAR(100) | Yes | Portuguese category. NULL = missing in source (610 products) |
| product_category_name_english | VARCHAR(100) | No | English category from the translation file, plus 2 manual translations. `unknown` when the category is missing |
| product_name_length | INTEGER | Yes | Characters in the product name. Source column `product_name_lenght` (misspelled) |
| product_description_length | INTEGER | Yes | Characters in the description. Source column `product_description_lenght` |
| product_photos_qty | INTEGER | Yes | Number of listing photos |
| product_weight_g | INTEGER | Yes | Weight in grams, > 0. Four source values of 0 set to NULL |
| product_length_cm | INTEGER | Yes | Package length, > 0 |
| product_height_cm | INTEGER | Yes | Package height, > 0 |
| product_width_cm | INTEGER | Yes | Package width, > 0 |

---

## Analytical views

Defined in [`sql/analytical_views.sql`](../sql/analytical_views.sql) and
[`sql/data_quality.sql`](../sql/data_quality.sql), and rebuilt on every pipeline run.

| View | Grain | Purpose |
|---|---|---|
| `state_reference` | State | 27 state codes with full names and IBGE macro-region |
| `order_facts` | Order | One row per order with revenue, primary category, status flags, lateness and fulfilment stage durations. The sales, operations and regional views build on it |
| `sales_dashboard` | Order item | Revenue by date, category and location. Exported for Tableau |
| `operations_dashboard` | Order | Delivery times, late flag, timeliness bucket and stage durations. Exported for Tableau |
| `regional_dashboard` | State | State KPIs with national comparisons and revenue/delivery segments. Exported for Tableau |
| `data_quality_summary` | Check | 36 data-quality checks measured in the database with severity and status. Exported for Tableau |

### Derived fields used across views

| Field | Rule |
|---|---|
| revenue | price + freight_value, only for orders not `canceled` or `unavailable` |
| primary_category | The category holding most of the order's value. 786 orders (0.8%) span more than one category |
| is_measurable_delivery | status `delivered`, delivery date present, `has_invalid_dates` = FALSE |
| is_late | delivery date later than the estimated delivery date |
| delivery_days | purchase → delivery to customer, in decimal days |
| seller_handoff_days | approval → handed to carrier |
| carrier_transit_days | handed to carrier → delivered |
| in_trend_window | purchase between January 2017 and August 2018 |
