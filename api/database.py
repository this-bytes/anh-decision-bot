import asyncpg
import os
from contextlib import asynccontextmanager

pool: asyncpg.Pool | None = None


async def init_pool() -> asyncpg.Pool:
    global pool
    if pool is None:
        pool = asyncpg.pool(
            host=os.getenv("DECISION_PG_HOST", "10.87.1.14"),
            port=int(os.getenv("DECISION_PG_PORT", "5432")),
            user=os.getenv("DECISION_PG_USER", "postgres"),
            password=os.getenv("DECISION_PG_PASS", ""),
            database=os.getenv("DECISION_PG_DATABASE", "anh_decisions"),
            min_size=2,
            max_size=10,
        )
    return pool


async def close_pool() -> None:
    global pool
    if pool is not None:
        await pool.close()
        pool = None


@asynccontextmanager
async def get_connection():
    global pool
    if pool is None:
        await init_pool()
    async with pool.acquire() as conn:
        yield conn
