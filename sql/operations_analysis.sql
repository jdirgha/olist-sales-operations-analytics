-- =====================================================================================
-- Operations analysis
-- Run all queries: python -m src.transformation sql/operations_analysis.sql
--
-- Definitions (used consistently across all operations queries):
--   Delivered order    = order_status = 'delivered' AND order_delivered_customer_date IS NOT NULL
--                        AND has_invalid_dates = FALSE (lifecycle dates out of order are excluded
--                        from time-based metrics; see data_quality_report.md).
--   Delivery time      = order_delivered_customer_date - order_purchase_timestamp, in days.
--   Estimated time     = order_estimated_delivery_date - order_purchase_timestamp, in days.
--   Late               = delivery DATE after the estimated delivery DATE. Every estimate is stored
--                        at 00:00, so delivery on the estimated day counts as on time.
--   Days vs estimate   = delivery date - estimated date (negative = early, positive = late).
--   Month              = purchase month; trend window 2017-01 .. 2018-08 (see sales_analysis.sql).
--   Cancellation rate  = canceled orders / all orders ('unavailable' reported separately).
-- =====================================================================================


-- name: delivery_time_summary
-- 1-2. Average and median delivery time, with spread.
WITH delivered AS (
    SELECT EXTRACT(EPOCH FROM (order_delivered_customer_date - order_purchase_timestamp)) / 86400.0 AS delivery_days
    FROM orders
    WHERE order_status = 'delivered'
      AND order_delivered_customer_date IS NOT NULL
      AND NOT has_invalid_dates
)
SELECT
    COUNT(*)                                                                         AS delivered_orders,
    ROUND(AVG(delivery_days)::numeric, 2)                                            AS avg_delivery_days,
    ROUND((PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY delivery_days))::numeric, 2)  AS median_delivery_days,
    ROUND((PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY delivery_days))::numeric, 2)  AS p90_delivery_days,
    ROUND(MIN(delivery_days)::numeric, 2)                                            AS min_delivery_days,
    ROUND(MAX(delivery_days)::numeric, 2)                                            AS max_delivery_days
FROM delivered;


-- name: estimated_vs_actual_delivery
-- 3. Estimated vs actual delivery time.
WITH delivered AS (
    SELECT
        EXTRACT(EPOCH FROM (order_delivered_customer_date - order_purchase_timestamp)) / 86400.0 AS actual_days,
        EXTRACT(EPOCH FROM (order_estimated_delivery_date - order_purchase_timestamp)) / 86400.0 AS estimated_days,
        order_delivered_customer_date::date - order_estimated_delivery_date::date                AS days_vs_estimate
    FROM orders
    WHERE order_status = 'delivered'
      AND order_delivered_customer_date IS NOT NULL
      AND NOT has_invalid_dates
)
SELECT
    ROUND(AVG(estimated_days)::numeric, 2)                                             AS avg_estimated_days,
    ROUND(AVG(actual_days)::numeric, 2)                                                AS avg_actual_days,
    ROUND(AVG(estimated_days - actual_days)::numeric, 2)                               AS avg_days_delivered_before_estimate,
    ROUND((PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY days_vs_estimate))::numeric, 2) AS median_days_vs_estimate,
    ROUND(AVG(days_vs_estimate) FILTER (WHERE days_vs_estimate > 0)::numeric, 2)       AS avg_days_late_when_late
FROM delivered;


-- name: delivery_timeliness_distribution
-- 3b. How far from the estimate orders arrive.
WITH delivered AS (
    SELECT order_delivered_customer_date::date - order_estimated_delivery_date::date AS days_vs_estimate
    FROM orders
    WHERE order_status = 'delivered'
      AND order_delivered_customer_date IS NOT NULL
      AND NOT has_invalid_dates
),
bucketed AS (
    SELECT
        CASE
            WHEN days_vs_estimate < -14 THEN '1. More than 14 days early'
            WHEN days_vs_estimate < -7  THEN '2. 8-14 days early'
            WHEN days_vs_estimate < 0   THEN '3. 1-7 days early'
            WHEN days_vs_estimate = 0   THEN '4. On estimated day'
            WHEN days_vs_estimate <= 3  THEN '5. 1-3 days late'
            WHEN days_vs_estimate <= 7  THEN '6. 4-7 days late'
            ELSE                             '7. More than 7 days late'
        END AS timeliness_bucket
    FROM delivered
)
SELECT
    timeliness_bucket,
    COUNT(*)                                            AS orders,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2)  AS pct_of_delivered
FROM bucketed
GROUP BY timeliness_bucket
ORDER BY timeliness_bucket;


-- name: late_delivery_rate
-- 4, 11, 12. Orders delivered on time vs late.
WITH delivered AS (
    SELECT order_delivered_customer_date::date > order_estimated_delivery_date::date AS is_late
    FROM orders
    WHERE order_status = 'delivered'
      AND order_delivered_customer_date IS NOT NULL
      AND NOT has_invalid_dates
)
SELECT
    COUNT(*)                                                        AS delivered_orders,
    COUNT(*) FILTER (WHERE NOT is_late)                             AS on_time_orders,
    COUNT(*) FILTER (WHERE is_late)                                 AS late_orders,
    ROUND(100.0 * COUNT(*) FILTER (WHERE NOT is_late) / COUNT(*), 2) AS on_time_pct,
    ROUND(100.0 * COUNT(*) FILTER (WHERE is_late) / COUNT(*), 2)     AS late_pct
FROM delivered;


-- name: late_deliveries_by_month
-- 5. Late deliveries and delivery time by purchase month.
WITH delivered AS (
    SELECT
        DATE_TRUNC('month', order_purchase_timestamp)::date                                      AS order_month,
        order_delivered_customer_date::date > order_estimated_delivery_date::date                AS is_late,
        EXTRACT(EPOCH FROM (order_delivered_customer_date - order_purchase_timestamp)) / 86400.0 AS actual_days,
        EXTRACT(EPOCH FROM (order_estimated_delivery_date - order_purchase_timestamp)) / 86400.0 AS estimated_days
    FROM orders
    WHERE order_status = 'delivered'
      AND order_delivered_customer_date IS NOT NULL
      AND NOT has_invalid_dates
      AND order_purchase_timestamp >= '2017-01-01'
      AND order_purchase_timestamp <  '2018-09-01'
)
SELECT
    order_month,
    COUNT(*)                                                      AS delivered_orders,
    COUNT(*) FILTER (WHERE is_late)                               AS late_orders,
    ROUND(100.0 * COUNT(*) FILTER (WHERE is_late) / COUNT(*), 2)   AS late_pct,
    ROUND(AVG(actual_days)::numeric, 2)                           AS avg_delivery_days,
    ROUND(AVG(estimated_days)::numeric, 2)                        AS avg_estimated_days
FROM delivered
GROUP BY order_month
ORDER BY order_month;


-- name: late_deliveries_by_state
-- 6. Late deliveries by customer state, ranked by late rate.
WITH delivered AS (
    SELECT
        c.customer_state,
        o.order_delivered_customer_date::date > o.order_estimated_delivery_date::date                AS is_late,
        EXTRACT(EPOCH FROM (o.order_delivered_customer_date - o.order_purchase_timestamp)) / 86400.0 AS actual_days
    FROM orders AS o
    JOIN customers AS c ON c.customer_id = o.customer_id
    WHERE o.order_status = 'delivered'
      AND o.order_delivered_customer_date IS NOT NULL
      AND NOT o.has_invalid_dates
)
SELECT
    customer_state,
    COUNT(*)                                                      AS delivered_orders,
    COUNT(*) FILTER (WHERE is_late)                               AS late_orders,
    ROUND(100.0 * COUNT(*) FILTER (WHERE is_late) / COUNT(*), 2)   AS late_pct,
    ROUND(AVG(actual_days)::numeric, 2)                           AS avg_delivery_days,
    RANK() OVER (ORDER BY 1.0 * COUNT(*) FILTER (WHERE is_late) / COUNT(*) DESC) AS late_rate_rank
FROM delivered
GROUP BY customer_state
ORDER BY late_pct DESC;


-- name: late_deliveries_by_category
-- 7. Late deliveries by product category. Each order is assigned its primary category
--    (the category holding most of the order's value; 0.8% of orders span several
--    categories), matching order_facts in analytical_views.sql. Categories with fewer
--    than 100 delivered orders are excluded because their rates are unstable.
WITH delivered AS (
    SELECT
        order_id,
        order_delivered_customer_date::date > order_estimated_delivery_date::date                AS is_late,
        EXTRACT(EPOCH FROM (order_delivered_customer_date - order_purchase_timestamp)) / 86400.0 AS actual_days
    FROM orders
    WHERE order_status = 'delivered'
      AND order_delivered_customer_date IS NOT NULL
      AND NOT has_invalid_dates
),
category_value AS (
    SELECT i.order_id, p.product_category_name_english AS product_category, SUM(i.price + i.freight_value) AS value
    FROM order_items AS i
    JOIN products AS p ON p.product_id = i.product_id
    GROUP BY i.order_id, p.product_category_name_english
),
order_categories AS (
    SELECT DISTINCT ON (order_id) order_id, product_category
    FROM category_value
    ORDER BY order_id, value DESC, product_category
)
SELECT
    oc.product_category,
    COUNT(*)                                                        AS delivered_orders,
    COUNT(*) FILTER (WHERE d.is_late)                               AS late_orders,
    ROUND(100.0 * COUNT(*) FILTER (WHERE d.is_late) / COUNT(*), 2)   AS late_pct,
    ROUND(AVG(d.actual_days)::numeric, 2)                           AS avg_delivery_days
FROM delivered AS d
JOIN order_categories AS oc ON oc.order_id = d.order_id
GROUP BY oc.product_category
HAVING COUNT(*) >= 100
ORDER BY late_pct DESC;


-- name: freight_cost_summary
-- 8. Average freight cost per item and per order, and for late vs on-time deliveries.
WITH order_freight AS (
    SELECT
        o.order_id,
        o.order_status,
        o.order_delivered_customer_date::date > o.order_estimated_delivery_date::date AS is_late,
        o.order_delivered_customer_date IS NOT NULL AND NOT o.has_invalid_dates      AS is_measurable_delivery,
        SUM(i.freight_value) AS freight,
        COUNT(*)             AS items
    FROM orders AS o
    JOIN order_items AS i ON i.order_id = o.order_id
    WHERE o.order_status NOT IN ('canceled', 'unavailable')
    GROUP BY o.order_id, o.order_status, o.order_delivered_customer_date, o.order_estimated_delivery_date, o.has_invalid_dates
)
SELECT
    ROUND(SUM(freight) / SUM(items), 2)                                                        AS avg_freight_per_item,
    ROUND(AVG(freight), 2)                                                                     AS avg_freight_per_order,
    ROUND(AVG(freight) FILTER (WHERE order_status = 'delivered' AND is_measurable_delivery AND NOT is_late), 2) AS avg_freight_on_time_orders,
    ROUND(AVG(freight) FILTER (WHERE order_status = 'delivered' AND is_measurable_delivery AND is_late), 2)     AS avg_freight_late_orders
FROM order_freight;


-- name: cancellation_rate_by_month
-- 9. Cancellation rate overall trend.
SELECT
    DATE_TRUNC('month', order_purchase_timestamp)::date                                           AS order_month,
    COUNT(*)                                                                                       AS orders,
    COUNT(*) FILTER (WHERE order_status = 'canceled')                                              AS canceled_orders,
    COUNT(*) FILTER (WHERE order_status = 'unavailable')                                           AS unavailable_orders,
    ROUND(100.0 * COUNT(*) FILTER (WHERE order_status = 'canceled') / COUNT(*), 2)                 AS cancellation_rate_pct,
    ROUND(100.0 * COUNT(*) FILTER (WHERE order_status IN ('canceled', 'unavailable')) / COUNT(*), 2) AS canceled_or_unavailable_pct
FROM orders
WHERE order_purchase_timestamp >= '2017-01-01'
  AND order_purchase_timestamp <  '2018-09-01'
GROUP BY order_month
ORDER BY order_month;


-- name: delivery_performance_by_status
-- 10. Order status distribution and how far each status got through the fulfilment process.
SELECT
    order_status,
    COUNT(*)                                                                      AS orders,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2)                            AS pct_of_orders,
    COUNT(order_approved_at)                                                      AS approved,
    COUNT(order_delivered_carrier_date)                                           AS handed_to_carrier,
    COUNT(order_delivered_customer_date)                                          AS delivered_to_customer,
    ROUND((AVG(EXTRACT(EPOCH FROM (order_approved_at - order_purchase_timestamp))) / 3600.0)::numeric, 2)
                                                                                  AS avg_hours_to_approval
FROM orders
GROUP BY order_status
ORDER BY orders DESC;


-- name: fulfilment_stage_times
-- Where delivery time is spent: approval, seller hand-off to carrier, carrier transit.
WITH delivered AS (
    SELECT
        EXTRACT(EPOCH FROM (order_approved_at - order_purchase_timestamp)) / 86400.0                AS approval_days,
        EXTRACT(EPOCH FROM (order_delivered_carrier_date - order_approved_at)) / 86400.0            AS seller_handoff_days,
        EXTRACT(EPOCH FROM (order_delivered_customer_date - order_delivered_carrier_date)) / 86400.0 AS carrier_transit_days,
        order_delivered_customer_date::date > order_estimated_delivery_date::date                  AS is_late
    FROM orders
    WHERE order_status = 'delivered'
      AND order_delivered_customer_date IS NOT NULL
      AND order_approved_at IS NOT NULL
      AND order_delivered_carrier_date IS NOT NULL
      AND NOT has_invalid_dates
)
SELECT
    CASE WHEN is_late THEN 'late' ELSE 'on_time' END  AS delivery_outcome,
    COUNT(*)                                          AS delivered_orders,
    ROUND(AVG(approval_days)::numeric, 2)             AS avg_approval_days,
    ROUND(AVG(seller_handoff_days)::numeric, 2)       AS avg_seller_handoff_days,
    ROUND(AVG(carrier_transit_days)::numeric, 2)      AS avg_carrier_transit_days
FROM delivered
GROUP BY is_late
ORDER BY delivery_outcome;


-- name: operations_kpis
-- Operational KPI dataset: one row of headline KPIs.
WITH delivered AS (
    SELECT
        EXTRACT(EPOCH FROM (order_delivered_customer_date - order_purchase_timestamp)) / 86400.0 AS actual_days,
        EXTRACT(EPOCH FROM (order_estimated_delivery_date - order_purchase_timestamp)) / 86400.0 AS estimated_days,
        order_delivered_customer_date::date > order_estimated_delivery_date::date                AS is_late
    FROM orders
    WHERE order_status = 'delivered'
      AND order_delivered_customer_date IS NOT NULL
      AND NOT has_invalid_dates
),
delivery AS (
    SELECT
        COUNT(*)                                                               AS delivered_orders,
        AVG(actual_days)                                                       AS avg_delivery_days,
        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY actual_days)               AS median_delivery_days,
        AVG(estimated_days)                                                    AS avg_estimated_days,
        100.0 * COUNT(*) FILTER (WHERE is_late) / COUNT(*)                     AS late_delivery_pct
    FROM delivered
),
status AS (
    SELECT
        COUNT(*)                                                               AS total_orders,
        100.0 * COUNT(*) FILTER (WHERE order_status = 'canceled') / COUNT(*)   AS cancellation_pct,
        100.0 * COUNT(*) FILTER (WHERE order_status = 'unavailable') / COUNT(*) AS unavailable_pct
    FROM orders
),
freight AS (
    SELECT AVG(order_freight) AS avg_freight_per_order
    FROM (
        SELECT SUM(i.freight_value) AS order_freight
        FROM order_items AS i
        JOIN orders AS o ON o.order_id = i.order_id
        WHERE o.order_status NOT IN ('canceled', 'unavailable')
        GROUP BY i.order_id
    ) AS per_order
)
SELECT
    s.total_orders,
    d.delivered_orders,
    ROUND(d.avg_delivery_days::numeric, 2)    AS avg_delivery_days,
    ROUND(d.median_delivery_days::numeric, 2) AS median_delivery_days,
    ROUND(d.avg_estimated_days::numeric, 2)   AS avg_estimated_days,
    ROUND(d.late_delivery_pct, 2)             AS late_delivery_pct,
    ROUND(s.cancellation_pct, 2)              AS cancellation_pct,
    ROUND(s.unavailable_pct, 2)               AS unavailable_pct,
    ROUND(f.avg_freight_per_order, 2)         AS avg_freight_per_order
FROM delivery AS d
CROSS JOIN status AS s
CROSS JOIN freight AS f;


-- name: operations_kpis_monthly
-- Operational KPI dataset by purchase month (trend window), for trend charts.
WITH order_freight AS (
    SELECT i.order_id, SUM(i.freight_value) AS freight
    FROM order_items AS i
    GROUP BY i.order_id
),
base AS (
    SELECT
        DATE_TRUNC('month', o.order_purchase_timestamp)::date AS order_month,
        o.order_status,
        o.order_status = 'delivered' AND o.order_delivered_customer_date IS NOT NULL AND NOT o.has_invalid_dates
                                                              AS is_measurable_delivery,
        o.order_delivered_customer_date::date > o.order_estimated_delivery_date::date AS is_late,
        EXTRACT(EPOCH FROM (o.order_delivered_customer_date - o.order_purchase_timestamp)) / 86400.0 AS actual_days,
        f.freight
    FROM orders AS o
    LEFT JOIN order_freight AS f ON f.order_id = o.order_id
    WHERE o.order_purchase_timestamp >= '2017-01-01'
      AND o.order_purchase_timestamp <  '2018-09-01'
)
SELECT
    order_month,
    COUNT(*)                                                                                       AS orders,
    COUNT(*) FILTER (WHERE is_measurable_delivery)                                                 AS delivered_orders,
    ROUND(AVG(actual_days) FILTER (WHERE is_measurable_delivery)::numeric, 2)                      AS avg_delivery_days,
    ROUND(100.0 * COUNT(*) FILTER (WHERE is_measurable_delivery AND is_late)
              / NULLIF(COUNT(*) FILTER (WHERE is_measurable_delivery), 0), 2)                      AS late_delivery_pct,
    ROUND(100.0 * COUNT(*) FILTER (WHERE order_status = 'canceled') / COUNT(*), 2)                 AS cancellation_pct,
    ROUND(AVG(freight) FILTER (WHERE order_status NOT IN ('canceled', 'unavailable')), 2)          AS avg_freight_per_order
FROM base
GROUP BY order_month
ORDER BY order_month;
