from fastapi import APIRouter, Query, HTTPException
from typing import Optional
from api.database import get_connection

router = APIRouter()


@router.get("/decisions")
async def list_decisions(
    target: Optional[str] = Query(None),
    kind: Optional[str] = Query(None),
    active: Optional[bool] = Query(None),
):
    async with get_connection() as conn:
        conditions = []
        params = []
        if target is not None:
            params.append(target)
            conditions.append(f"target = ${len(params)}")
        if kind is not None:
            params.append(kind)
            conditions.append(f"kind = ${len(params)}")
        if active is not None:
            params.append(active)
            conditions.append(f"active = ${len(params)}")

        where = " AND ".join(conditions) if conditions else "1=1"
        query = f"SELECT * FROM decisions WHERE {where} ORDER BY created_at DESC"
        rows = await conn.fetch(query, *params)
        return [dict(r) for r in rows]
