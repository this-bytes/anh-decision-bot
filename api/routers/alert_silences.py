from fastapi import APIRouter, Query
from typing import Optional
from app.database import get_connection

router = APIRouter()


@router.get("/alert_silences")
async def list_alert_silences(active: Optional[bool] = Query(None)):
    async with get_connection() as conn:
        conditions = ["last_seen IS NOT NULL"]
        params = []
        if active is not None:
            params.append(active)
            conditions.append(f"active = ${len(params)}")

        where = " AND ".join(conditions)
        query = f"SELECT * FROM alert_silences WHERE {where} ORDER BY created_at DESC"
        rows = await conn.fetch(query, *params)
        return [dict(r) for r in rows]
