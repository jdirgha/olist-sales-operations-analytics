-- =====================================================================================
-- Sales analysis
-- Run all queries: python -m src.transformation sql/sales_analysis.sql
--
-- Definitions (used consistently across all sales queries):
--   Revenue          = SUM(price + freight_value) from order_items, i.e. what the customer
--                      paid for the items including shipping.
--   Revenue orders   = orders whose status is NOT 'canceled' or 'unavailable'.
--                      Canceled/unavailable orders are reported separately, never as revenue.
--   Completed orders = order_status = 'delivered'.
--   Order date       = order_purchase_timestamp.
--   Trend window     = complete months 2017-01 .. 2018-08. Earlier months are sparse
--                      (Nov 2016 has no orders) and Sep/Oct 2018 only contain the data
--                      cut-off (20 orders, 19 canceled/unavailable), so month-over-month
--                      comparisons outside the window would be misleading.
--   Customers        = distinct customer_unique_id (customer_id is issued per order).
-- Each query is preceded by "-- name: <query_name>" so it can be run and exported on its own.
-- =====================================================================================


-- name: total_revenue
-- 1. Total revenue, split into product and freight, plus gross value of all orders for context.
SELECT
    ROUND(SUM(i.price + i.freight_value) FILTER (WHERE o.order_status NOT IN ('canceled', 'unavailable')), 2) AS total_revenue,
    ROUND(SUM(i.price)                   FILTER (WHERE o.order_status NOT IN ('canceled', 'unavailable')), 2) AS product_revenue,
    ROUND(SUM(i.freight_value)           FILTER (WHERE o.order_status NOT IN ('canceled', 'unavailable')), 2) AS freight_revenue,
    ROUND(SUM(i.price + i.freight_value) FILTER (WHERE o.order_status IN ('canceled', 'unavailable')), 2)     AS canceled_order_value,
    ROUND(SUM(i.price + i.freight_value), 2)                                                                   AS gross_order_value_all_statuses
FROM orders AS o
JOIN order_items AS i ON i.order_id = o.order_id;


-- name: total_orders
-- 2. Order and customer counts.
SELECT
    COUNT(*)                                                                         AS total_orders,
    COUNT(*) FILTER (WHERE o.order_status NOT IN ('canceled', 'unavailable'))        AS revenue_orders,
    COUNT(*) FILTER (WHERE o.order_status = 'delivered')                             AS delivered_orders,
    COUNT(*) FILTER (WHERE NOT EXISTS (SELECT 1 FROM order_items AS i WHERE i.order_id = o.order_id)) AS orders_without_items,
    COUNT(DISTINCT c.customer_unique_id)                                             AS total_customers
FROM orders AS o
JOIN customers AS c ON c.customer_id = o.customer_id;


-- name: monthly_revenue
-- 3. Monthly revenue within the trend window.
SELECT
    DATE_TRUNC('month', o.order_purchase_timestamp)::date AS order_month,
    ROUND(SUM(i.price + i.freight_value), 2)             AS revenue
FROM orders AS o
JOIN order_items AS i ON i.order_id = o.order_id
WHERE o.order_status NOT IN ('canceled', 'unavailable')
  AND o.order_purchase_timestamp >= '2017-01-01'
  AND o.order_purchase_timestamp <  '2018-09-01'
GROUP BY order_month
ORDER BY order_month;


-- name: monthly_revenue_mom
-- 4. Month-over-month revenue change.
WITH monthly AS (
    SELECT
        DATE_TRUNC('month', o.order_purchase_timestamp)::date AS order_month,
        SUM(i.price + i.freight_value)                       AS revenue
    FROM orders AS o
    JOIN order_items AS i ON i.order_id = o.order_id
    WHERE o.order_status NOT IN ('canceled', 'unavailable')
      AND o.order_purchase_timestamp >= '2017-01-01'
      AND o.order_purchase_timestamp <  '2018-09-01'
    GROUP BY order_month
)
SELECT
    order_month,
    ROUND(revenue, 2)                                                        AS revenue,
    ROUND(LAG(revenue) OVER (ORDER BY order_month), 2)                       AS previous_month_revenue,
    ROUND(revenue - LAG(revenue) OVER (ORDER BY order_month), 2)             AS revenue_change,
    ROUND(100 * (revenue / NULLIF(LAG(revenue) OVER (ORDER BY order_month), 0) - 1), 2) AS revenue_change_pct
FROM monthly
ORDER BY order_month;


-- name: monthly_order_volume
-- 5. Monthly order volume: all orders placed, and orders that generated revenue.
SELECT
    DATE_TRUNC('month', o.order_purchase_timestamp)::date                  AS order_month,
    COUNT(*)                                                                AS orders_placed,
    COUNT(*) FILTER (WHERE o.order_status NOT IN ('canceled', 'unavailable')) AS revenue_orders,
    COUNT(*) FILTER (WHERE o.order_status IN ('canceled', 'unavailable'))     AS canceled_or_unavailable
FROM orders AS o
WHERE o.order_purchase_timestamp >= '2017-01-01'
  AND o.order_purchase_timestamp <  '2018-09-01'
GROUP BY order_month
ORDER BY order_month;


-- name: average_order_value
-- 6. Average order value (AOV) = revenue / revenue orders that have items.
WITH order_revenue AS (
    SELECT o.order_id, SUM(i.price + i.freight_value) AS revenue
    FROM orders AS o
    JOIN order_items AS i ON i.order_id = o.order_id
    WHERE o.order_status NOT IN ('canceled', 'unavailable')
    GROUP BY o.order_id
)
SELECT
    COUNT(*)                                                        AS orders,
    ROUND(AVG(revenue), 2)                                          AS average_order_value,
    ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY revenue)::numeric, 2) AS median_order_value,
    ROUND(MIN(revenue), 2)                                          AS min_order_value,
    ROUND(MAX(revenue), 2)                                          AS max_order_value
FROM order_revenue;


-- name: revenue_by_category
-- 7. Revenue by product category (English names; 'unknown' = category missing in source).
SELECT
    p.product_category_name_english      AS product_category,
    COUNT(DISTINCT o.order_id)            AS orders,
    COUNT(*)                              AS items_sold,
    ROUND(SUM(i.price + i.freight_value), 2) AS revenue,
    ROUND(AVG(i.price), 2)                AS average_item_price
FROM orders AS o
JOIN order_items AS i ON i.order_id = o.order_id
JOIN products AS p ON p.product_id = i.product_id
WHERE o.order_status NOT IN ('canceled', 'unavailable')
GROUP BY p.product_category_name_english
ORDER BY revenue DESC;


-- name: top_10_categories
-- 8. Top 10 categories by revenue.
WITH category_revenue AS (
    SELECT p.product_category_name_english AS product_category, SUM(i.price + i.freight_value) AS revenue
    FROM orders AS o
    JOIN order_items AS i ON i.order_id = o.order_id
    JOIN products AS p ON p.product_id = i.product_id
    WHERE o.order_status NOT IN ('canceled', 'unavailable')
    GROUP BY p.product_category_name_english
),
ranked AS (
    SELECT product_category, revenue, RANK() OVER (ORDER BY revenue DESC) AS revenue_rank
    FROM category_revenue
)
SELECT revenue_rank, product_category, ROUND(revenue, 2) AS revenue
FROM ranked
WHERE revenue_rank <= 10
ORDER BY revenue_rank;


-- name: revenue_by_state
-- 9. Revenue by customer state.
SELECT
    c.customer_state,
    COUNT(DISTINCT o.order_id)               AS orders,
    COUNT(DISTINCT c.customer_unique_id)     AS customers,
    ROUND(SUM(i.price + i.freight_value), 2) AS revenue,
    ROUND(100 * SUM(i.price + i.freight_value) / SUM(SUM(i.price + i.freight_value)) OVER (), 2) AS revenue_share_pct
FROM orders AS o
JOIN customers AS c ON c.customer_id = o.customer_id
JOIN order_items AS i ON i.order_id = o.order_id
WHERE o.order_status NOT IN ('canceled', 'unavailable')
GROUP BY c.customer_state
ORDER BY revenue DESC;


-- name: revenue_by_month_category
-- 10. Revenue by month and category within the trend window.
SELECT
    DATE_TRUNC('month', o.order_purchase_timestamp)::date AS order_month,
    p.product_category_name_english                      AS product_category,
    COUNT(DISTINCT o.order_id)                           AS orders,
    ROUND(SUM(i.price + i.freight_value), 2)             AS revenue
FROM orders AS o
JOIN order_items AS i ON i.order_id = o.order_id
JOIN products AS p ON p.product_id = i.product_id
WHERE o.order_status NOT IN ('canceled', 'unavailable')
  AND o.order_purchase_timestamp >= '2017-01-01'
  AND o.order_purchase_timestamp <  '2018-09-01'
GROUP BY order_month, p.product_category_name_english
ORDER BY order_month, revenue DESC;


-- name: average_freight_cost
-- 11. Freight cost per item and per order, and freight relative to product price.
WITH order_freight AS (
    SELECT o.order_id, SUM(i.freight_value) AS freight, SUM(i.price) AS product_value
    FROM orders AS o
    JOIN order_items AS i ON i.order_id = o.order_id
    WHERE o.order_status NOT IN ('canceled', 'unavailable')
    GROUP BY o.order_id
)
SELECT
    ROUND(SUM(freight) / (SELECT COUNT(*) FROM order_items AS i JOIN orders AS o ON o.order_id = i.order_id
                          WHERE o.order_status NOT IN ('canceled', 'unavailable')), 2) AS average_freight_per_item,
    ROUND(AVG(freight), 2)                                      AS average_freight_per_order,
    ROUND(100 * SUM(freight) / SUM(product_value), 2)           AS freight_as_pct_of_product_value
FROM order_freight;


-- name: completed_order_revenue
-- 12. Revenue from completed (delivered) orders and its share of total revenue.
SELECT
    ROUND(SUM(i.price + i.freight_value) FILTER (WHERE o.order_status = 'delivered'), 2)  AS completed_revenue,
    ROUND(SUM(i.price + i.freight_value) FILTER (WHERE o.order_status <> 'delivered'), 2) AS in_progress_revenue,
    ROUND(100 * SUM(i.price + i.freight_value) FILTER (WHERE o.order_status = 'delivered')
              / SUM(i.price + i.freight_value), 2)                                         AS completed_share_pct
FROM orders AS o
JOIN order_items AS i ON i.order_id = o.order_id
WHERE o.order_status NOT IN ('canceled', 'unavailable');


-- name: cancellation_rate
-- 13. Cancelled order rate. 'unavailable' (seller could not fulfil) is shown separately
--     and combined, because both mean the sale did not happen.
SELECT
    COUNT(*)                                                                    AS total_orders,
    COUNT(*) FILTER (WHERE order_status = 'canceled')                           AS canceled_orders,
    COUNT(*) FILTER (WHERE order_status = 'unavailable')                        AS unavailable_orders,
    ROUND(100.0 * COUNT(*) FILTER (WHERE order_status = 'canceled') / COUNT(*), 2)    AS cancellation_rate_pct,
    ROUND(100.0 * COUNT(*) FILTER (WHERE order_status IN ('canceled', 'unavailable')) / COUNT(*), 2)
                                                                                AS canceled_or_unavailable_rate_pct
FROM orders;


-- name: category_revenue_contribution
-- 14. Each category's share of revenue and the cumulative share (Pareto view).
WITH category_revenue AS (
    SELECT p.product_category_name_english AS product_category, SUM(i.price + i.freight_value) AS revenue
    FROM orders AS o
    JOIN order_items AS i ON i.order_id = o.order_id
    JOIN products AS p ON p.product_id = i.product_id
    WHERE o.order_status NOT IN ('canceled', 'unavailable')
    GROUP BY p.product_category_name_english
)
SELECT
    RANK() OVER (ORDER BY revenue DESC)                                          AS revenue_rank,
    product_category,
    ROUND(revenue, 2)                                                            AS revenue,
    ROUND(100 * revenue / SUM(revenue) OVER (), 2)                               AS revenue_share_pct,
    ROUND(100 * SUM(revenue) OVER (ORDER BY revenue DESC ROWS UNBOUNDED PRECEDING)
              / SUM(revenue) OVER (), 2)                                         AS cumulative_share_pct
FROM category_revenue
ORDER BY revenue DESC;


-- name: category_trend_recent_vs_prior
-- 15. Declining / growing categories: last 6 complete months (2018-03..2018-08) vs the
--     6 months before (2017-09..2018-02). Share change removes the effect of overall growth.
--     Only categories with >= 50 revenue orders across both periods, to avoid noise.
WITH period_revenue AS (
    SELECT
        p.product_category_name_english AS product_category,
        CASE WHEN o.order_purchase_timestamp >= '2018-03-01' THEN 'recent' ELSE 'prior' END AS period,
        o.order_id,
        i.price + i.freight_value AS revenue
    FROM orders AS o
    JOIN order_items AS i ON i.order_id = o.order_id
    JOIN products AS p ON p.product_id = i.product_id
    WHERE o.order_status NOT IN ('canceled', 'unavailable')
      AND o.order_purchase_timestamp >= '2017-09-01'
      AND o.order_purchase_timestamp <  '2018-09-01'
),
by_category AS (
    SELECT
        product_category,
        SUM(revenue) FILTER (WHERE period = 'prior')  AS prior_revenue,
        SUM(revenue) FILTER (WHERE period = 'recent') AS recent_revenue,
        COUNT(DISTINCT order_id)                      AS orders
    FROM period_revenue
    GROUP BY product_category
),
with_share AS (
    SELECT
        product_category,
        orders,
        COALESCE(prior_revenue, 0)  AS prior_revenue,
        COALESCE(recent_revenue, 0) AS recent_revenue,
        100 * COALESCE(prior_revenue, 0)  / SUM(COALESCE(prior_revenue, 0))  OVER () AS prior_share_pct,
        100 * COALESCE(recent_revenue, 0) / SUM(COALESCE(recent_revenue, 0)) OVER () AS recent_share_pct
    FROM by_category
)
SELECT
    product_category,
    ROUND(prior_revenue, 2)                                              AS prior_6m_revenue,
    ROUND(recent_revenue, 2)                                             AS recent_6m_revenue,
    ROUND(100 * (recent_revenue / NULLIF(prior_revenue, 0) - 1), 2)      AS revenue_change_pct,
    ROUND(prior_share_pct, 2)                                            AS prior_share_pct,
    ROUND(recent_share_pct, 2)                                           AS recent_share_pct,
    ROUND(recent_share_pct - prior_share_pct, 2)                         AS share_change_pp
FROM with_share
WHERE orders >= 50
ORDER BY revenue_change_pct ASC NULLS LAST;
