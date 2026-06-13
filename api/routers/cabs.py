from fastapi import APIRouter, Query
from typing import Optional
from app.database import get_connection

router = APIRouter()


@router.get("/cabs")
async def list_cabs(status: Optional[str] = Query(None)):
    async with get_connection() as conn:
        if status is not None:
            query = "SELECT * FROM cabs WHERE status = $1 ORDER BY created_at DESC"
            rows = await conn.fetch(query, status)
        else:
            query = "SELECT * FROM cabs ORDER BY created_at DESC"
            rows = await conn.fetch(query)
        return [dict(r) for r in rows]
