-- =====================================================================================
-- Analytical views for Tableau
-- Created by the pipeline after loading (src/transformation.py -> create_views).
--
--   state_reference       27 Brazilian states: code, name, IBGE macro-region.
--   order_facts           Base view, one row per order, all order-level metrics.
--   sales_dashboard       One row per order item (plus one row per order without items),
--                         so revenue can be filtered by date, state, category and status.
--   operations_dashboard  One row per order: delivery, lateness, fulfilment stages, freight.
--   regional_dashboard    One row per state: all-time totals, national comparison, segment.
--
-- Metric definitions match sql/sales_analysis.sql and sql/operations_analysis.sql.
-- Views are dropped and recreated so column changes are always applied.
-- =====================================================================================

DROP VIEW IF EXISTS regional_dashboard, operations_dashboard, sales_dashboard, order_facts, state_reference CASCADE;


CREATE VIEW state_reference AS
SELECT state_code, state_name, macro_region
FROM (VALUES
    ('AC', 'Acre', 'North'),                ('AL', 'Alagoas', 'Northeast'),
    ('AM', 'Amazonas', 'North'),            ('AP', 'Amapá', 'North'),
    ('BA', 'Bahia', 'Northeast'),           ('CE', 'Ceará', 'Northeast'),
    ('DF', 'Distrito Federal', 'Center-West'), ('ES', 'Espírito Santo', 'Southeast'),
    ('GO', 'Goiás', 'Center-West'),         ('MA', 'Maranhão', 'Northeast'),
    ('MG', 'Minas Gerais', 'Southeast'),    ('MS', 'Mato Grosso do Sul', 'Center-West'),
    ('MT', 'Mato Grosso', 'Center-West'),   ('PA', 'Pará', 'North'),
    ('PB', 'Paraíba', 'Northeast'),         ('PE', 'Pernambuco', 'Northeast'),
    ('PI', 'Piauí', 'Northeast'),           ('PR', 'Paraná', 'South'),
    ('RJ', 'Rio de Janeiro', 'Southeast'),  ('RN', 'Rio Grande do Norte', 'Northeast'),
    ('RO', 'Rondônia', 'North'),            ('RR', 'Roraima', 'North'),
    ('RS', 'Rio Grande do Sul', 'South'),   ('SC', 'Santa Catarina', 'South'),
    ('SE', 'Sergipe', 'Northeast'),         ('SP', 'São Paulo', 'Southeast'),
    ('TO', 'Tocantins', 'North')
) AS states (state_code, state_name, macro_region);


CREATE VIEW order_facts AS
WITH item_totals AS (
    SELECT
        order_id,
        COUNT(*)                     AS item_count,
        SUM(price)                   AS product_value,
        SUM(freight_value)           AS freight_value,
        SUM(price + freight_value)   AS order_value
    FROM order_items
    GROUP BY order_id
),
category_value AS (
    SELECT i.order_id, p.product_category_name_english AS product_category, SUM(i.price + i.freight_value) AS value
    FROM order_items AS i
    JOIN products AS p ON p.product_id = i.product_id
    GROUP BY i.order_id, p.product_category_name_english
),
primary_category AS (
    -- Category holding most of the order's value; ties broken alphabetically.
    SELECT DISTINCT ON (order_id) order_id, product_category
    FROM category_value
    ORDER BY order_id, value DESC, product_category
),
base AS (
    SELECT
        o.order_id,
        c.customer_unique_id,
        c.customer_state,
        o.order_status,
        o.order_purchase_timestamp,
        o.order_approved_at,
        o.order_delivered_carrier_date,
        o.order_delivered_customer_date,
        o.order_estimated_delivery_date,
        o.has_invalid_dates,
        o.order_status NOT IN ('canceled', 'unavailable') AS is_revenue_order,
        o.order_status = 'delivered'
            AND o.order_delivered_customer_date IS NOT NULL
            AND NOT o.has_invalid_dates                   AS is_measurable_delivery
    FROM orders AS o
    JOIN customers AS c ON c.customer_id = o.customer_id
)
SELECT
    b.order_id,
    b.customer_unique_id,
    b.customer_state,
    s.state_name,
    s.macro_region,
    b.order_status,
    b.order_purchase_timestamp,
    b.order_purchase_timestamp::date                                               AS order_purchase_date,
    DATE_TRUNC('month', b.order_purchase_timestamp)::date                          AS order_month,
    b.order_purchase_timestamp >= '2017-01-01' AND b.order_purchase_timestamp < '2018-09-01'
                                                                                   AS in_trend_window,
    pc.product_category                                                            AS primary_category,
    COALESCE(it.item_count, 0)                                                     AS item_count,
    it.product_value,
    it.freight_value,
    it.order_value,
    CASE WHEN b.is_revenue_order THEN it.order_value END                           AS revenue,
    b.is_revenue_order,
    b.order_status = 'canceled'                                                    AS is_canceled,
    b.order_status = 'unavailable'                                                 AS is_unavailable,
    b.is_measurable_delivery,
    CASE WHEN b.is_measurable_delivery
         THEN b.order_delivered_customer_date::date > b.order_estimated_delivery_date::date END AS is_late,
    CASE WHEN b.is_measurable_delivery
         THEN EXTRACT(EPOCH FROM (b.order_delivered_customer_date - b.order_purchase_timestamp)) / 86400.0 END
                                                                                   AS delivery_days,
    CASE WHEN b.is_measurable_delivery
         THEN EXTRACT(EPOCH FROM (b.order_estimated_delivery_date - b.order_purchase_timestamp)) / 86400.0 END
                                                                                   AS estimated_days,
    CASE WHEN b.is_measurable_delivery
         THEN b.order_delivered_customer_date::date - b.order_estimated_delivery_date::date END
                                                                                   AS days_vs_estimate,
    CASE WHEN NOT b.has_invalid_dates
         THEN EXTRACT(EPOCH FROM (b.order_approved_at - b.order_purchase_timestamp)) / 3600.0 END
                                                                                   AS approval_hours,
    CASE WHEN NOT b.has_invalid_dates
         THEN EXTRACT(EPOCH FROM (b.order_delivered_carrier_date - b.order_approved_at)) / 86400.0 END
                                                                                   AS seller_handoff_days,
    CASE WHEN NOT b.has_invalid_dates
         THEN EXTRACT(EPOCH FROM (b.order_delivered_customer_date - b.order_delivered_carrier_date)) / 86400.0 END
                                                                                   AS carrier_transit_days,
    b.has_invalid_dates
FROM base AS b
LEFT JOIN state_reference AS s ON s.state_code = b.customer_state
LEFT JOIN item_totals AS it ON it.order_id = b.order_id
LEFT JOIN primary_category AS pc ON pc.order_id = b.order_id;


CREATE VIEW sales_dashboard AS
SELECT
    f.order_id,
    i.order_item_id,
    f.customer_unique_id,
    f.customer_state,
    f.state_name,
    f.macro_region,
    f.order_status,
    f.order_purchase_date,
    f.order_month,
    f.in_trend_window,
    f.is_revenue_order,
    p.product_category_name_english                                 AS product_category,
    i.price,
    i.freight_value,
    i.price + i.freight_value                                       AS item_value,
    CASE WHEN f.is_revenue_order THEN i.price + i.freight_value END AS revenue
FROM order_facts AS f
LEFT JOIN order_items AS i ON i.order_id = f.order_id
LEFT JOIN products AS p ON p.product_id = i.product_id;


CREATE VIEW operations_dashboard AS
SELECT
    order_id,
    customer_unique_id,
    customer_state,
    state_name,
    macro_region,
    order_status,
    order_purchase_date,
    order_month,
    in_trend_window,
    primary_category,
    item_count,
    ROUND(freight_value, 2)                        AS freight_value,
    ROUND(revenue, 2)                              AS revenue,
    is_revenue_order,
    is_canceled,
    is_unavailable,
    is_measurable_delivery,
    is_late,
    CASE WHEN is_late THEN 'Late' WHEN NOT is_late THEN 'On time' END AS delivery_outcome,
    CASE
        WHEN days_vs_estimate IS NULL THEN NULL
        WHEN days_vs_estimate < -14   THEN '1. More than 14 days early'
        WHEN days_vs_estimate < -7    THEN '2. 8-14 days early'
        WHEN days_vs_estimate < 0     THEN '3. 1-7 days early'
        WHEN days_vs_estimate = 0     THEN '4. On estimated day'
        WHEN days_vs_estimate <= 3    THEN '5. 1-3 days late'
        WHEN days_vs_estimate <= 7    THEN '6. 4-7 days late'
        ELSE                               '7. More than 7 days late'
    END                                            AS timeliness_bucket,
    ROUND(delivery_days::numeric, 2)               AS delivery_days,
    ROUND(estimated_days::numeric, 2)              AS estimated_days,
    days_vs_estimate,
    ROUND(approval_hours::numeric, 2)              AS approval_hours,
    ROUND(seller_handoff_days::numeric, 2)         AS seller_handoff_days,
    ROUND(carrier_transit_days::numeric, 2)        AS carrier_transit_days,
    has_invalid_dates
FROM order_facts;


CREATE VIEW regional_dashboard AS
WITH by_state AS (
    SELECT
        customer_state,
        state_name,
        macro_region,
        SUM(revenue)                                                     AS revenue,
        COUNT(*) FILTER (WHERE is_revenue_order)                         AS revenue_orders,
        COUNT(DISTINCT customer_unique_id)                               AS customers,
        AVG(revenue)                                                     AS avg_order_value,
        AVG(freight_value) FILTER (WHERE is_revenue_order)               AS avg_freight_per_order,
        COUNT(*) FILTER (WHERE is_measurable_delivery)                   AS delivered_orders,
        COUNT(*) FILTER (WHERE is_late)                                  AS late_orders,
        AVG(delivery_days)                                               AS avg_delivery_days,
        SUM(revenue) FILTER (WHERE is_late)                              AS late_order_revenue
    FROM order_facts
    GROUP BY customer_state, state_name, macro_region
),
national AS (
    SELECT
        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY revenue)             AS median_state_revenue,
        100.0 * SUM(late_orders) / SUM(delivered_orders)                 AS late_pct
    FROM by_state
),
national_exact AS (
    SELECT AVG(delivery_days) AS avg_delivery_days
    FROM order_facts
)
SELECT
    s.customer_state,
    s.state_name,
    s.macro_region,
    ROUND(s.revenue, 2)                                                          AS revenue,
    ROUND(100 * s.revenue / SUM(s.revenue) OVER (), 2)                           AS revenue_share_pct,
    RANK() OVER (ORDER BY s.revenue DESC)                                        AS revenue_rank,
    s.revenue_orders,
    s.customers,
    ROUND(s.avg_order_value, 2)                                                  AS avg_order_value,
    ROUND(s.avg_freight_per_order, 2)                                            AS avg_freight_per_order,
    s.delivered_orders,
    s.late_orders,
    ROUND(100.0 * s.late_orders / NULLIF(s.delivered_orders, 0), 2)              AS late_pct,
    ROUND(n.late_pct, 2)                                                         AS national_late_pct,
    ROUND(100.0 * s.late_orders / NULLIF(s.delivered_orders, 0) - n.late_pct, 2) AS late_pct_vs_national_pp,
    ROUND(s.avg_delivery_days::numeric, 2)                                       AS avg_delivery_days,
    ROUND(ne.avg_delivery_days::numeric, 2)                                      AS national_avg_delivery_days,
    ROUND(COALESCE(s.late_order_revenue, 0), 2)                                  AS late_order_revenue,
    CASE WHEN s.revenue >= n.median_state_revenue THEN 'Higher revenue' ELSE 'Lower revenue' END AS revenue_tier,
    CASE WHEN 100.0 * s.late_orders / NULLIF(s.delivered_orders, 0) > n.late_pct
         THEN 'Late rate above national' ELSE 'Late rate at/below national' END  AS delivery_tier,
    CASE WHEN s.revenue >= n.median_state_revenue THEN 'Higher revenue' ELSE 'Lower revenue' END
        || ' / ' ||
    CASE WHEN 100.0 * s.late_orders / NULLIF(s.delivered_orders, 0) > n.late_pct
         THEN 'late rate above national' ELSE 'late rate at/below national' END  AS segment,
    s.delivered_orders < 100                                                     AS small_sample
FROM by_state AS s
CROSS JOIN national AS n
CROSS JOIN national_exact AS ne;
