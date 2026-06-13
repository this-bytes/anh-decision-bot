from fastapi import APIRouter, Query, HTTPException
from typing import Optional
from app.database import get_connection

router = APIRouter()

VALID_ENTITIES = {"decisions", "cabs", "alert_silences", "audit_log"}


@router.get("/audit_log")
async def get_audit_log(
    entity: Optional[str] = Query(None),
    id: Optional[int] = Query(None),
):
    async with get_connection() as conn:
        conditions = []
        params = []
        if entity is not None:
            if entity not in VALID_ENTITIES:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid entity. Must be one of: {', '.join(sorted(VALID_ENTITIES))}",
                )
            params.append(entity)
            conditions.append(f"entity = ${len(params)}")
        if id is not None:
            params.append(id)
            conditions.append(f"row_id = ${len(params)}")

        where = " AND ".join(conditions) if conditions else "1=1"
        query = f"SELECT * FROM audit_log WHERE {where} ORDER BY created_at DESC"
        rows = await conn.fetch(query, *params)
        return [dict(r) for r in rows]
