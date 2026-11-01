-- Useful analysis queries for Asol Dam (PostgreSQL). Good SQL practice:
-- window functions, CTEs, percentiles and date filtering on real data.

-- 1. Latest price of every product
SELECT DISTINCT ON (p.id)
       p.id, p.title, s.price, s.original_price, s.captured_at
FROM products p
JOIN price_snapshots s ON s.product_id = p.id
ORDER BY p.id, s.captured_at DESC;

-- 2. Lowest, usual (median) and highest price over the last 90 days
SELECT p.id, p.title,
       MIN(s.price)                                        AS lowest,
       PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY s.price) AS usual,
       MAX(s.price)                                        AS highest,
       COUNT(*)                                            AS checks
FROM products p
JOIN price_snapshots s ON s.product_id = p.id
WHERE s.captured_at >= now() - INTERVAL '90 days'
GROUP BY p.id, p.title;

-- 3. "Claimed" vs "real" discount right now
WITH latest AS (
    SELECT DISTINCT ON (product_id) product_id, price, original_price
    FROM price_snapshots
    ORDER BY product_id, captured_at DESC
), usual AS (
    SELECT product_id, PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY price) AS usual_price
    FROM price_snapshots
    WHERE captured_at >= now() - INTERVAL '30 days'
    GROUP BY product_id
)
SELECT p.title,
       l.price,
       ROUND(100 * (l.original_price - l.price) / NULLIF(l.original_price, 0), 1) AS claimed_off_pct,
       ROUND(100 * (u.usual_price   - l.price) / NULLIF(u.usual_price,   0), 1) AS real_off_pct
FROM latest l
JOIN usual u   ON u.product_id = l.product_id
JOIN products p ON p.id = l.product_id
ORDER BY claimed_off_pct - real_off_pct DESC;   -- biggest liars first

-- 4. Price changes day by day (LAG window function)
SELECT product_id, captured_at, price,
       price - LAG(price) OVER (PARTITION BY product_id ORDER BY captured_at) AS change
FROM price_snapshots
ORDER BY product_id, captured_at;

-- 5. Products whose price jumped more than 10% in the 14 days before a sale date
SELECT p.title, MIN(s.price) AS before_low, MAX(s.price) AS before_high
FROM products p
JOIN price_snapshots s ON s.product_id = p.id
WHERE s.captured_at BETWEEN DATE '2026-10-28' AND DATE '2026-11-11'
GROUP BY p.title
HAVING MAX(s.price) > 1.10 * MIN(s.price);
