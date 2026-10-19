import os
import aiosqlite

DB_PATH = "data/state.db"

# Cria a pasta data se não existir (importante pro Render)
os.makedirs("data", exist_ok=True)

SCHEMA = """
CREATE TABLE IF NOT EXISTS processed_orders (
    order_id TEXT PRIMARY KEY,
    processed_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS pending_carts (
    user_id INTEGER PRIMARY KEY,
    order_id TEXT,
    total TEXT,
    items TEXT,
    checkout_url TEXT,
    created_at INTEGER NOT NULL,
    last_nudged_at INTEGER,
    attempts INTEGER DEFAULT 0,
    converted INTEGER DEFAULT 0
);
"""

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(SCHEMA)
        await db.commit()

async def order_already_processed(order_id: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT 1 FROM processed_orders WHERE order_id = ?", (order_id,)) as cur:
            return await cur.fetchone() is not None

async def mark_order_processed(order_id: str, ts: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO processed_orders (order_id, processed_at) VALUES (?, ?)", (order_id, ts))
        await db.execute("UPDATE pending_carts SET converted = 1 WHERE order_id = ?", (order_id,))
        await db.commit()

async def add_pending_cart(user_id: int, order_id: str, total: str, items: str, url: str, ts: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT OR REPLACE INTO pending_carts
               (user_id, order_id, total, items, checkout_url, created_at, attempts, converted)
               VALUES (?, ?, ?, ?, ?, ?, 0, 0)""",
            (user_id, order_id, total, items, url, ts),
        )
        await db.commit()

async def get_carts_to_nudge(now: int, interval_sec: int, max_attempts: int):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            """SELECT user_id, order_id, total, items, checkout_url, attempts, last_nudged_at, created_at
               FROM pending_carts
               WHERE converted = 0 AND attempts < ?
                 AND (last_nudged_at IS NULL OR (? - last_nudged_at) >= ?)""",
            (max_attempts, now, interval_sec),
        ) as cur:
            return await cur.fetchall()

async def register_nudge(user_id: int, ts: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE pending_carts SET attempts = attempts + 1, last_nudged_at = ? WHERE user_id = ?",
            (ts, user_id),
        )
        await db.commit()