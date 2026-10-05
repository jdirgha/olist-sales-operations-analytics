-- =====================================================================================
-- Regional analysis
-- Run all queries: python -m src.transformation sql/regional_analysis.sql
--
-- Uses the same definitions as sales_analysis.sql and operations_analysis.sql:
--   Revenue            = SUM(price + freight_value) of orders not 'canceled'/'unavailable'.
--   Delivered order    = 'delivered' with a delivery date and has_invalid_dates = FALSE.
--   Late               = delivery date after estimated delivery date.
--   Region             = customer_state (where the order was delivered to).
--
-- Segmentation (objective thresholds, no judgement labels):
--   Revenue tier  : 'Higher revenue' if state revenue >= median state revenue, else 'Lower revenue'.
--   Delivery tier : 'Late rate above national' if state late % > national late %,
--                   else 'Late rate at/below national'.
--   States with < 100 delivered orders are flagged small_sample: their rates are less reliable.
-- =====================================================================================


-- name: state_performance
-- Revenue, volume, AOV and delivery metrics per state, with national comparison.
WITH order_revenue AS (
    SELECT i.order_id, SUM(i.price + i.freight_value) AS revenue, SUM(i.freight_value) AS freight
    FROM order_items AS i
    GROUP BY i.order_id
),
order_level AS (
    SELECT
        c.customer_state,
        o.order_id,
        c.customer_unique_id,
        o.order_status NOT IN ('canceled', 'unavailable')                                  AS is_revenue_order,
        o.order_status = 'delivered' AND o.order_delivered_customer_date IS NOT NULL
            AND NOT o.has_invalid_dates                                                    AS is_measurable_delivery,
        o.order_delivered_customer_date::date > o.order_estimated_delivery_date::date     AS is_late,
        EXTRACT(EPOCH FROM (o.order_delivered_customer_date - o.order_purchase_timestamp)) / 86400.0 AS delivery_days,
        r.revenue,
        r.freight
    FROM orders AS o
    JOIN customers AS c ON c.customer_id = o.customer_id
    LEFT JOIN order_revenue AS r ON r.order_id = o.order_id
),
by_state AS (
    SELECT
        customer_state,
        COUNT(*) FILTER (WHERE is_revenue_order)                                  AS revenue_orders,
        COUNT(DISTINCT customer_unique_id)                                        AS customers,
        SUM(revenue) FILTER (WHERE is_revenue_order)                              AS revenue,
        AVG(revenue) FILTER (WHERE is_revenue_order)                              AS avg_order_value,
        AVG(freight) FILTER (WHERE is_revenue_order)                              AS avg_freight_per_order,
        COUNT(*) FILTER (WHERE is_measurable_delivery)                            AS delivered_orders,
        COUNT(*) FILTER (WHERE is_measurable_delivery AND is_late)                AS late_orders,
        AVG(delivery_days) FILTER (WHERE is_measurable_delivery)                  AS avg_delivery_days,
        SUM(revenue) FILTER (WHERE is_measurable_delivery AND is_late)            AS late_order_revenue
    FROM order_level
    GROUP BY customer_state
),
national AS (
    SELECT
        100.0 * COUNT(*) FILTER (WHERE is_measurable_delivery AND is_late)
              / COUNT(*) FILTER (WHERE is_measurable_delivery)                    AS late_pct,
        AVG(delivery_days) FILTER (WHERE is_measurable_delivery)                  AS avg_delivery_days,
        AVG(revenue) FILTER (WHERE is_revenue_order)                              AS avg_order_value
    FROM order_level
)
SELECT
    s.customer_state,
    RANK() OVER (ORDER BY s.revenue DESC)                                          AS revenue_rank,
    ROUND(s.revenue, 2)                                                            AS revenue,
    ROUND(100 * s.revenue / SUM(s.revenue) OVER (), 2)                             AS revenue_share_pct,
    s.revenue_orders,
    s.customers,
    ROUND(s.avg_order_value, 2)                                                    AS avg_order_value,
    ROUND(s.avg_order_value - n.avg_order_value, 2)                                AS aov_vs_national,
    ROUND(s.avg_freight_per_order, 2)                                              AS avg_freight_per_order,
    s.delivered_orders,
    s.late_orders,
    ROUND(100.0 * s.late_orders / NULLIF(s.delivered_orders, 0), 2)                AS late_pct,
    ROUND(100.0 * s.late_orders / NULLIF(s.delivered_orders, 0) - n.late_pct, 2)   AS late_pct_vs_national_pp,
    ROUND(s.avg_delivery_days::numeric, 2)                                         AS avg_delivery_days,
    ROUND((s.avg_delivery_days - n.avg_delivery_days)::numeric, 2)                 AS delivery_days_vs_national,
    ROUND(COALESCE(s.late_order_revenue, 0), 2)                                    AS late_order_revenue,
    s.delivered_orders < 100                                                       AS small_sample
FROM by_state AS s
CROSS JOIN national AS n
ORDER BY s.revenue DESC;


-- name: state_segments
-- Each state placed in a revenue tier x delivery tier segment.
WITH order_revenue AS (
    SELECT i.order_id, SUM(i.price + i.freight_value) AS revenue
    FROM order_items AS i
    GROUP BY i.order_id
),
order_level AS (
    SELECT
        c.customer_state,
        o.order_status NOT IN ('canceled', 'unavailable')                              AS is_revenue_order,
        o.order_status = 'delivered' AND o.order_delivered_customer_date IS NOT NULL
            AND NOT o.has_invalid_dates                                                AS is_measurable_delivery,
        o.order_delivered_customer_date::date > o.order_estimated_delivery_date::date AS is_late,
        r.revenue
    FROM orders AS o
    JOIN customers AS c ON c.customer_id = o.customer_id
    LEFT JOIN order_revenue AS r ON r.order_id = o.order_id
),
by_state AS (
    SELECT
        customer_state,
        SUM(revenue) FILTER (WHERE is_revenue_order)                    AS revenue,
        COUNT(*) FILTER (WHERE is_measurable_delivery)                  AS delivered_orders,
        100.0 * COUNT(*) FILTER (WHERE is_measurable_delivery AND is_late)
              / NULLIF(COUNT(*) FILTER (WHERE is_measurable_delivery), 0) AS late_pct
    FROM order_level
    GROUP BY customer_state
),
thresholds AS (
    SELECT
        (SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY revenue) FROM by_state) AS median_state_revenue,
        (SELECT 100.0 * COUNT(*) FILTER (WHERE is_late) / COUNT(*)
         FROM order_level WHERE is_measurable_delivery)                              AS national_late_pct
)
SELECT
    s.customer_state,
    ROUND(s.revenue, 2)                                                         AS revenue,
    ROUND(t.median_state_revenue::numeric, 2)                                   AS median_state_revenue,
    ROUND(s.late_pct, 2)                                                        AS late_pct,
    ROUND(t.national_late_pct, 2)                                               AS national_late_pct,
    CASE WHEN s.revenue >= t.median_state_revenue THEN 'Higher revenue' ELSE 'Lower revenue' END AS revenue_tier,
    CASE WHEN s.late_pct > t.national_late_pct
         THEN 'Late rate above national' ELSE 'Late rate at/below national' END  AS delivery_tier,
    CASE WHEN s.revenue >= t.median_state_revenue THEN 'Higher revenue' ELSE 'Lower revenue' END
        || ' / ' ||
    CASE WHEN s.late_pct > t.national_late_pct
         THEN 'late rate above national' ELSE 'late rate at/below national' END  AS segment,
    s.delivered_orders < 100                                                    AS small_sample
FROM by_state AS s
CROSS JOIN thresholds AS t
ORDER BY segment, s.revenue DESC;


-- name: segment_summary
-- Size of each segment: how much revenue and how many late orders sit in each.
WITH order_revenue AS (
    SELECT i.order_id, SUM(i.price + i.freight_value) AS revenue
    FROM order_items AS i
    GROUP BY i.order_id
),
order_level AS (
    SELECT
        c.customer_state,
        o.order_status NOT IN ('canceled', 'unavailable')                              AS is_revenue_order,
        o.order_status = 'delivered' AND o.order_delivered_customer_date IS NOT NULL
            AND NOT o.has_invalid_dates                                                AS is_measurable_delivery,
        o.order_delivered_customer_date::date > o.order_estimated_delivery_date::date AS is_late,
        r.revenue
    FROM orders AS o
    JOIN customers AS c ON c.customer_id = o.customer_id
    LEFT JOIN order_revenue AS r ON r.order_id = o.order_id
),
by_state AS (
    SELECT
        customer_state,
        SUM(revenue) FILTER (WHERE is_revenue_order)                    AS revenue,
        COUNT(*) FILTER (WHERE is_revenue_order)                        AS revenue_orders,
        COUNT(*) FILTER (WHERE is_measurable_delivery)                  AS delivered_orders,
        COUNT(*) FILTER (WHERE is_measurable_delivery AND is_late)      AS late_orders
    FROM order_level
    GROUP BY customer_state
),
thresholds AS (
    SELECT
        (SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY revenue) FROM by_state)   AS median_state_revenue,
        (SELECT 100.0 * SUM(late_orders) / SUM(delivered_orders) FROM by_state)        AS national_late_pct
),
segmented AS (
    SELECT
        s.customer_state,
        s.revenue,
        s.revenue_orders,
        s.delivered_orders,
        s.late_orders,
        CASE WHEN s.revenue >= t.median_state_revenue THEN 'Higher revenue' ELSE 'Lower revenue' END
            || ' / ' ||
        CASE WHEN 100.0 * s.late_orders / NULLIF(s.delivered_orders, 0) > t.national_late_pct
             THEN 'late rate above national' ELSE 'late rate at/below national' END AS segment
    FROM by_state AS s
    CROSS JOIN thresholds AS t
)
SELECT
    segment,
    COUNT(*)                                                       AS states,
    STRING_AGG(customer_state, ', ' ORDER BY revenue DESC)         AS state_list,
    ROUND(SUM(revenue), 2)                                         AS revenue,
    ROUND(100 * SUM(revenue) / SUM(SUM(revenue)) OVER (), 2)       AS revenue_share_pct,
    SUM(revenue_orders)                                            AS revenue_orders,
    SUM(late_orders)                                               AS late_orders,
    ROUND(100.0 * SUM(late_orders) / SUM(SUM(late_orders)) OVER (), 2) AS share_of_all_late_orders_pct,
    ROUND(100.0 * SUM(late_orders) / SUM(delivered_orders), 2)     AS segment_late_pct
FROM segmented
GROUP BY segment
ORDER BY revenue DESC;


-- name: macro_region_performance
-- The five official Brazilian macro-regions (IBGE), for a higher-level view.
WITH order_revenue AS (
    SELECT i.order_id, SUM(i.price + i.freight_value) AS revenue
    FROM order_items AS i
    GROUP BY i.order_id
),
order_level AS (
    SELECT
        CASE
            WHEN c.customer_state IN ('AC', 'AM', 'AP', 'PA', 'RO', 'RR', 'TO')                   THEN 'North'
            WHEN c.customer_state IN ('AL', 'BA', 'CE', 'MA', 'PB', 'PE', 'PI', 'RN', 'SE')       THEN 'Northeast'
            WHEN c.customer_state IN ('DF', 'GO', 'MS', 'MT')                                     THEN 'Center-West'
            WHEN c.customer_state IN ('ES', 'MG', 'RJ', 'SP')                                     THEN 'Southeast'
            WHEN c.customer_state IN ('PR', 'RS', 'SC')                                           THEN 'South'
        END                                                                            AS macro_region,
        o.order_status NOT IN ('canceled', 'unavailable')                              AS is_revenue_order,
        o.order_status = 'delivered' AND o.order_delivered_customer_date IS NOT NULL
            AND NOT o.has_invalid_dates                                                AS is_measurable_delivery,
        o.order_delivered_customer_date::date > o.order_estimated_delivery_date::date AS is_late,
        EXTRACT(EPOCH FROM (o.order_delivered_customer_date - o.order_purchase_timestamp)) / 86400.0 AS delivery_days,
        r.revenue
    FROM orders AS o
    JOIN customers AS c ON c.customer_id = o.customer_id
    LEFT JOIN order_revenue AS r ON r.order_id = o.order_id
)
SELECT
    macro_region,
    ROUND(SUM(revenue) FILTER (WHERE is_revenue_order), 2)                                   AS revenue,
    ROUND(100 * SUM(revenue) FILTER (WHERE is_revenue_order)
              / SUM(SUM(revenue) FILTER (WHERE is_revenue_order)) OVER (), 2)                AS revenue_share_pct,
    COUNT(*) FILTER (WHERE is_revenue_order)                                                 AS revenue_orders,
    ROUND(AVG(revenue) FILTER (WHERE is_revenue_order), 2)                                   AS avg_order_value,
    ROUND(100.0 * COUNT(*) FILTER (WHERE is_measurable_delivery AND is_late)
              / COUNT(*) FILTER (WHERE is_measurable_delivery), 2)                           AS late_pct,
    ROUND(AVG(delivery_days) FILTER (WHERE is_measurable_delivery)::numeric, 2)              AS avg_delivery_days
FROM order_level
GROUP BY macro_region
ORDER BY revenue DESC;
