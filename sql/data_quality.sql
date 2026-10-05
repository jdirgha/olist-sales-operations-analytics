-- =====================================================================================
-- Data quality checks on the loaded database
-- Creates the view data_quality_summary (one row per check), used by the Tableau
-- data-quality section. Run after analytical_views.sql (uses state_reference).
--
-- Python validation (src/validation.py) gates the load; these SQL checks re-measure the
-- data inside PostgreSQL so the dashboard reports on exactly what it displays.
--
-- Severity -> status when record_count > 0:
--   critical -> FAIL     would corrupt KPIs; should never happen after validation
--   warning  -> WARNING  real issue, handled in analysis (excluded or labelled)
--   info     -> INFO     expected by design (e.g. no delivery date for undelivered orders)
-- record_count = 0 -> PASS for every severity.
-- =====================================================================================

DROP VIEW IF EXISTS data_quality_summary;

CREATE VIEW data_quality_summary AS
WITH totals AS (
    SELECT
        (SELECT COUNT(*) FROM customers)   AS customers,
        (SELECT COUNT(*) FROM orders)      AS orders,
        (SELECT COUNT(*) FROM order_items) AS order_items,
        (SELECT COUNT(*) FROM payments)    AS payments,
        (SELECT COUNT(*) FROM products)    AS products
),
checks (check_category, table_name, check_name, severity, record_count, total_records) AS (
    -- Missing values ---------------------------------------------------------------
    SELECT 'Missing values', 'orders', 'Delivered order without delivery date', 'warning',
           (SELECT COUNT(*) FROM orders WHERE order_status = 'delivered' AND order_delivered_customer_date IS NULL),
           (SELECT orders FROM totals)
    UNION ALL
    SELECT 'Missing values', 'orders', 'No delivery date (order not delivered)', 'info',
           (SELECT COUNT(*) FROM orders WHERE order_status <> 'delivered' AND order_delivered_customer_date IS NULL),
           (SELECT orders FROM totals)
    UNION ALL
    SELECT 'Missing values', 'orders', 'No approval date', 'info',
           (SELECT COUNT(*) FROM orders WHERE order_approved_at IS NULL),
           (SELECT orders FROM totals)
    UNION ALL
    SELECT 'Missing values', 'products', 'Product category missing (shown as unknown)', 'warning',
           (SELECT COUNT(*) FROM products WHERE product_category_name IS NULL),
           (SELECT products FROM totals)
    UNION ALL
    SELECT 'Missing values', 'products', 'Weight or dimensions missing', 'info',
           (SELECT COUNT(*) FROM products
            WHERE product_weight_g IS NULL OR product_length_cm IS NULL
               OR product_height_cm IS NULL OR product_width_cm IS NULL),
           (SELECT products FROM totals)
    UNION ALL
    SELECT 'Missing values', 'payments', 'Installments missing (invalid 0 in source)', 'warning',
           (SELECT COUNT(*) FROM payments WHERE payment_installments IS NULL),
           (SELECT payments FROM totals)

    -- Duplicate records ------------------------------------------------------------
    UNION ALL
    SELECT 'Duplicate records', 'customers', 'Duplicate customer_id', 'critical',
           (SELECT COUNT(*) - COUNT(DISTINCT customer_id) FROM customers), (SELECT customers FROM totals)
    UNION ALL
    SELECT 'Duplicate records', 'orders', 'Duplicate order_id', 'critical',
           (SELECT COUNT(*) - COUNT(DISTINCT order_id) FROM orders), (SELECT orders FROM totals)
    UNION ALL
    SELECT 'Duplicate records', 'order_items', 'Duplicate order_id + order_item_id', 'critical',
           (SELECT COUNT(*) - COUNT(DISTINCT (order_id, order_item_id)) FROM order_items), (SELECT order_items FROM totals)
    UNION ALL
    SELECT 'Duplicate records', 'payments', 'Duplicate order_id + payment_sequential', 'critical',
           (SELECT COUNT(*) - COUNT(DISTINCT (order_id, payment_sequential)) FROM payments), (SELECT payments FROM totals)
    UNION ALL
    SELECT 'Duplicate records', 'products', 'Duplicate product_id', 'critical',
           (SELECT COUNT(*) - COUNT(DISTINCT product_id) FROM products), (SELECT products FROM totals)

    -- Invalid values ---------------------------------------------------------------
    UNION ALL
    SELECT 'Invalid values', 'order_items', 'Negative price', 'critical',
           (SELECT COUNT(*) FROM order_items WHERE price < 0), (SELECT order_items FROM totals)
    UNION ALL
    SELECT 'Invalid values', 'order_items', 'Zero price', 'warning',
           (SELECT COUNT(*) FROM order_items WHERE price = 0), (SELECT order_items FROM totals)
    UNION ALL
    SELECT 'Invalid values', 'order_items', 'Negative freight', 'critical',
           (SELECT COUNT(*) FROM order_items WHERE freight_value < 0), (SELECT order_items FROM totals)
    UNION ALL
    SELECT 'Invalid values', 'payments', 'Negative payment value', 'critical',
           (SELECT COUNT(*) FROM payments WHERE payment_value < 0), (SELECT payments FROM totals)
    UNION ALL
    SELECT 'Invalid values', 'payments', 'Zero payment value', 'warning',
           (SELECT COUNT(*) FROM payments WHERE payment_value = 0), (SELECT payments FROM totals)
    UNION ALL
    SELECT 'Invalid values', 'customers', 'Zip code prefix not 5 digits', 'warning',
           (SELECT COUNT(*) FROM customers WHERE customer_zip_code_prefix !~ '^[0-9]{5}$'), (SELECT customers FROM totals)

    -- Invalid dates ----------------------------------------------------------------
    UNION ALL
    SELECT 'Invalid dates', 'orders', 'Delivered before purchase', 'critical',
           (SELECT COUNT(*) FROM orders WHERE order_delivered_customer_date < order_purchase_timestamp),
           (SELECT orders FROM totals)
    UNION ALL
    SELECT 'Invalid dates', 'orders', 'Estimated delivery before purchase', 'critical',
           (SELECT COUNT(*) FROM orders WHERE order_estimated_delivery_date < order_purchase_timestamp),
           (SELECT orders FROM totals)
    UNION ALL
    SELECT 'Invalid dates', 'orders', 'Approved before purchase', 'warning',
           (SELECT COUNT(*) FROM orders WHERE order_approved_at < order_purchase_timestamp), (SELECT orders FROM totals)
    UNION ALL
    SELECT 'Invalid dates', 'orders', 'Handed to carrier before purchase', 'warning',
           (SELECT COUNT(*) FROM orders WHERE order_delivered_carrier_date < order_purchase_timestamp),
           (SELECT orders FROM totals)
    UNION ALL
    SELECT 'Invalid dates', 'orders', 'Delivered to customer before handed to carrier', 'warning',
           (SELECT COUNT(*) FROM orders WHERE order_delivered_customer_date < order_delivered_carrier_date),
           (SELECT orders FROM totals)
    UNION ALL
    SELECT 'Invalid dates', 'order_items', 'Shipping limit after last purchase date in data', 'warning',
           (SELECT COUNT(*) FROM order_items
            WHERE shipping_limit_date > (SELECT MAX(order_purchase_timestamp) FROM orders)),
           (SELECT order_items FROM totals)

    -- Orphan records ---------------------------------------------------------------
    UNION ALL
    SELECT 'Orphan records', 'orders', 'Order without items', 'warning',
           (SELECT COUNT(*) FROM orders AS o WHERE NOT EXISTS (SELECT 1 FROM order_items AS i WHERE i.order_id = o.order_id)),
           (SELECT orders FROM totals)
    UNION ALL
    SELECT 'Orphan records', 'orders', 'Order without payments', 'warning',
           (SELECT COUNT(*) FROM orders AS o WHERE NOT EXISTS (SELECT 1 FROM payments AS p WHERE p.order_id = o.order_id)),
           (SELECT orders FROM totals)
    UNION ALL
    SELECT 'Orphan records', 'customers', 'Customer without orders', 'warning',
           (SELECT COUNT(*) FROM customers AS c WHERE NOT EXISTS (SELECT 1 FROM orders AS o WHERE o.customer_id = c.customer_id)),
           (SELECT customers FROM totals)
    UNION ALL
    SELECT 'Orphan records', 'products', 'Product never ordered', 'warning',
           (SELECT COUNT(*) FROM products AS p WHERE NOT EXISTS (SELECT 1 FROM order_items AS i WHERE i.product_id = p.product_id)),
           (SELECT products FROM totals)

    -- Unmatched foreign keys -------------------------------------------------------
    UNION ALL
    SELECT 'Unmatched foreign keys', 'orders', 'customer_id not in customers', 'critical',
           (SELECT COUNT(*) FROM orders AS o LEFT JOIN customers AS c ON c.customer_id = o.customer_id WHERE c.customer_id IS NULL),
           (SELECT orders FROM totals)
    UNION ALL
    SELECT 'Unmatched foreign keys', 'order_items', 'order_id not in orders', 'critical',
           (SELECT COUNT(*) FROM order_items AS i LEFT JOIN orders AS o ON o.order_id = i.order_id WHERE o.order_id IS NULL),
           (SELECT order_items FROM totals)
    UNION ALL
    SELECT 'Unmatched foreign keys', 'order_items', 'product_id not in products', 'critical',
           (SELECT COUNT(*) FROM order_items AS i LEFT JOIN products AS p ON p.product_id = i.product_id WHERE p.product_id IS NULL),
           (SELECT order_items FROM totals)
    UNION ALL
    SELECT 'Unmatched foreign keys', 'payments', 'order_id not in orders', 'critical',
           (SELECT COUNT(*) FROM payments AS p LEFT JOIN orders AS o ON o.order_id = p.order_id WHERE o.order_id IS NULL),
           (SELECT payments FROM totals)

    -- Inconsistent categories ------------------------------------------------------
    UNION ALL
    SELECT 'Inconsistent categories', 'orders', 'Unknown order status', 'warning',
           (SELECT COUNT(*) FROM orders
            WHERE order_status NOT IN ('created', 'approved', 'invoiced', 'processing', 'shipped',
                                       'delivered', 'canceled', 'unavailable')),
           (SELECT orders FROM totals)
    UNION ALL
    SELECT 'Inconsistent categories', 'orders', 'Canceled order with a delivery date', 'warning',
           (SELECT COUNT(*) FROM orders WHERE order_status = 'canceled' AND order_delivered_customer_date IS NOT NULL),
           (SELECT orders FROM totals)
    UNION ALL
    SELECT 'Inconsistent categories', 'payments', 'Payment type not_defined or unknown', 'warning',
           (SELECT COUNT(*) FROM payments WHERE payment_type NOT IN ('credit_card', 'boleto', 'voucher', 'debit_card')),
           (SELECT payments FROM totals)
    UNION ALL
    SELECT 'Inconsistent categories', 'customers', 'State code not a Brazilian state', 'warning',
           (SELECT COUNT(*) FROM customers AS c
            WHERE NOT EXISTS (SELECT 1 FROM state_reference AS s WHERE s.state_code = c.customer_state)),
           (SELECT customers FROM totals)
    UNION ALL
    SELECT 'Inconsistent categories', 'products', 'Category name variants differing only by case/spacing', 'warning',
           (SELECT COUNT(*) FROM (
                SELECT LOWER(TRIM(product_category_name))
                FROM products
                WHERE product_category_name IS NOT NULL
                GROUP BY LOWER(TRIM(product_category_name))
                HAVING COUNT(DISTINCT product_category_name) > 1
            ) AS variants),
           (SELECT products FROM totals)
)
SELECT
    check_category,
    table_name,
    check_name,
    severity,
    record_count,
    total_records,
    ROUND(100.0 * record_count / NULLIF(total_records, 0), 2) AS pct_of_records,
    CASE
        WHEN record_count = 0        THEN 'PASS'
        WHEN severity = 'critical'   THEN 'FAIL'
        WHEN severity = 'warning'    THEN 'WARNING'
        ELSE 'INFO'
    END                                                       AS status
FROM checks;


-- name: data_quality_summary
-- All checks (the view above).
SELECT check_category, table_name, check_name, severity, record_count, total_records, pct_of_records, status
FROM data_quality_summary
ORDER BY check_category, table_name, check_name;


-- name: data_quality_by_category
-- Roll-up for the dashboard's summary tiles.
SELECT
    check_category,
    COUNT(*)                                       AS checks,
    COUNT(*) FILTER (WHERE status = 'PASS')        AS passed,
    COUNT(*) FILTER (WHERE status = 'WARNING')     AS warnings,
    COUNT(*) FILTER (WHERE status = 'FAIL')        AS failed,
    COUNT(*) FILTER (WHERE status = 'INFO')        AS info,
    SUM(record_count) FILTER (WHERE severity <> 'info') AS affected_records
FROM data_quality_summary
GROUP BY check_category
ORDER BY check_category;
