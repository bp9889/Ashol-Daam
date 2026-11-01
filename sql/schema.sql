-- Asol Dam database schema (PostgreSQL flavour).
-- The app creates these tables automatically through SQLAlchemy (app/models.py);
-- this file is the same design written as plain SQL, for reading and practice.

CREATE TABLE products (
    id               SERIAL PRIMARY KEY,
    source           VARCHAR(32)  NOT NULL,          -- 'daraz', later 'amazon', 'pickaboo', ...
    external_id      VARCHAR(64)  NOT NULL,          -- the store's own id for the product
    url              TEXT         NOT NULL,
    title            TEXT         NOT NULL,
    image_url        TEXT,
    variant          VARCHAR(160),                   -- chosen size/option, e.g. '30 ML Spray'
    delivery         NUMERIC(10,2),                  -- standard delivery fee on its page (0 = free)
    category         VARCHAR(32),                    -- the store's category id, e.g. '9543' (phone cases)
    currency         VARCHAR(8)   NOT NULL DEFAULT 'BDT',
    is_demo          BOOLEAN      NOT NULL DEFAULT FALSE,
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    last_checked_at  TIMESTAMPTZ,
    CONSTRAINT uq_product_source_external UNIQUE (source, external_id)
);

-- One row every time we look at a product's price.
CREATE TABLE price_snapshots (
    id              SERIAL PRIMARY KEY,
    product_id      INTEGER       NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    price           NUMERIC(12,2) NOT NULL,          -- what the buyer pays
    original_price  NUMERIC(12,2),                   -- the crossed-out "was" price
    in_stock        BOOLEAN       NOT NULL DEFAULT TRUE,
    captured_at     TIMESTAMPTZ   NOT NULL DEFAULT now()
);

CREATE INDEX ix_snapshots_product_time ON price_snapshots (product_id, captured_at);

-- What other sellers charge for the same product (gives a verdict on day one).
CREATE TABLE market_checks (
    id            SERIAL PRIMARY KEY,
    product_id    INTEGER       NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    checked_at    TIMESTAMPTZ   NOT NULL DEFAULT now(),
    query         TEXT          NOT NULL,           -- what we searched for
    seller_count  INTEGER       NOT NULL DEFAULT 0, -- how many matching listings we kept
    median_price  NUMERIC(12,2),
    low_price     NUMERIC(12,2),
    high_price    NUMERIC(12,2),
    listings      JSON          NOT NULL,           -- the matching listings (seller, title, price, url)
    detailed      BOOLEAN       NOT NULL DEFAULT FALSE -- sellers' pages opened (sizes, sale prices, delivery)
);

CREATE INDEX ix_market_product_time ON market_checks (product_id, checked_at);

-- Phase 2: Telegram price-drop alerts.
CREATE TABLE alerts (
    id                   SERIAL PRIMARY KEY,
    product_id           INTEGER       NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    token                VARCHAR(32)   NOT NULL UNIQUE,   -- travels in the t.me/<bot>?start=<token> link
    chat_id              VARCHAR(32),                     -- filled in when the person presses Start
    target_price         NUMERIC(12,2),                   -- NULL = tell me about any real drop
    baseline_price       NUMERIC(12,2) NOT NULL,          -- price when the alert was set
    active               BOOLEAN       NOT NULL DEFAULT TRUE,
    created_at           TIMESTAMPTZ   NOT NULL DEFAULT now(),
    last_notified_at     TIMESTAMPTZ,
    last_notified_price  NUMERIC(12,2)
);

CREATE INDEX ix_alerts_product ON alerts (product_id);
CREATE INDEX ix_alerts_chat ON alerts (chat_id);

-- "This browser checked this product": keeps each visitor's "Recently checked" list private.
-- visitor = a random id from a cookie (no name, no login).
CREATE TABLE visits (
    id          SERIAL PRIMARY KEY,
    visitor     VARCHAR(64)  NOT NULL,
    product_id  INTEGER      NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    added_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT uq_visit_visitor_product UNIQUE (visitor, product_id)
);
CREATE INDEX ix_visits_visitor ON visits (visitor);
