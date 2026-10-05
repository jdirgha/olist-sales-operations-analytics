-- Sales & Operations Analytics - relational model for the cleaned Olist data.
--
--   customers 1 --- * orders 1 --- * order_items * --- 1 products
--                        1
--                        |
--                        * payments
--
-- Tables are created if missing; data is refreshed by src/database.py
-- (TRUNCATE + COPY in a single transaction). Constraints mirror the critical
-- rules in src/validation.py so the database itself rejects invalid data.

CREATE TABLE IF NOT EXISTS customers (
    customer_id              VARCHAR(32)  PRIMARY KEY,
    customer_unique_id       VARCHAR(32)  NOT NULL,
    customer_zip_code_prefix CHAR(5)      NOT NULL,
    customer_city            VARCHAR(100) NOT NULL,
    customer_state           CHAR(2)      NOT NULL
);

CREATE TABLE IF NOT EXISTS products (
    product_id                    VARCHAR(32)  PRIMARY KEY,
    product_category_name         VARCHAR(100),                -- NULL = category unknown in source
    product_name_length           INTEGER,
    product_description_length    INTEGER,
    product_photos_qty            INTEGER,
    product_weight_g              INTEGER      CHECK (product_weight_g > 0),
    product_length_cm             INTEGER      CHECK (product_length_cm > 0),
    product_height_cm             INTEGER      CHECK (product_height_cm > 0),
    product_width_cm              INTEGER      CHECK (product_width_cm > 0),
    product_category_name_english VARCHAR(100) NOT NULL           -- 'unknown' when category is NULL
);

CREATE TABLE IF NOT EXISTS orders (
    order_id                      VARCHAR(32) PRIMARY KEY,
    customer_id                   VARCHAR(32) NOT NULL REFERENCES customers (customer_id),
    order_status                  VARCHAR(20) NOT NULL,
    order_purchase_timestamp      TIMESTAMP   NOT NULL,
    order_approved_at             TIMESTAMP,                      -- NULL = not approved
    order_delivered_carrier_date  TIMESTAMP,                      -- NULL = not handed to carrier
    order_delivered_customer_date TIMESTAMP,                      -- NULL = not delivered
    order_estimated_delivery_date TIMESTAMP   NOT NULL,
    has_invalid_dates             BOOLEAN     NOT NULL DEFAULT FALSE,
    CONSTRAINT chk_delivered_after_purchase
        CHECK (order_delivered_customer_date IS NULL OR order_delivered_customer_date >= order_purchase_timestamp),
    CONSTRAINT chk_estimate_after_purchase
        CHECK (order_estimated_delivery_date >= order_purchase_timestamp)
);

CREATE TABLE IF NOT EXISTS order_items (
    order_id            VARCHAR(32)   NOT NULL REFERENCES orders (order_id),
    order_item_id       SMALLINT      NOT NULL,
    product_id          VARCHAR(32)   NOT NULL REFERENCES products (product_id),
    seller_id           VARCHAR(32)   NOT NULL,
    shipping_limit_date TIMESTAMP     NOT NULL,
    price               NUMERIC(10,2) NOT NULL CHECK (price >= 0),
    freight_value       NUMERIC(10,2) NOT NULL CHECK (freight_value >= 0),
    PRIMARY KEY (order_id, order_item_id)
);

CREATE TABLE IF NOT EXISTS payments (
    order_id             VARCHAR(32)   NOT NULL REFERENCES orders (order_id),
    payment_sequential   SMALLINT      NOT NULL,
    payment_type         VARCHAR(20)   NOT NULL,
    payment_installments SMALLINT      CHECK (payment_installments > 0),   -- NULL = invalid 0 in source
    payment_value        NUMERIC(10,2) NOT NULL CHECK (payment_value >= 0),
    PRIMARY KEY (order_id, payment_sequential)
);

-- order_id lookups on order_items and payments use the leading column of their primary keys.
CREATE INDEX IF NOT EXISTS idx_orders_customer_id        ON orders (customer_id);
CREATE INDEX IF NOT EXISTS idx_orders_purchase_timestamp ON orders (order_purchase_timestamp);
CREATE INDEX IF NOT EXISTS idx_orders_status             ON orders (order_status);
CREATE INDEX IF NOT EXISTS idx_order_items_product_id    ON order_items (product_id);
CREATE INDEX IF NOT EXISTS idx_customers_unique_id       ON customers (customer_unique_id);
CREATE INDEX IF NOT EXISTS idx_customers_state           ON customers (customer_state);
