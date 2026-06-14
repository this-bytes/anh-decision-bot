from contextlib import asynccontextmanager
from fastapi import FastAPI
from database import init_pool, close_pool
from routers import decisions, cabs, alert_silences, audit_log


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_pool()
    yield
    await close_pool()


app = FastAPI(title="anh-decision-api", lifespan=lifespan)

app.include_router(decisions.router, tags=["decisions"])
app.include_router(cabs.router, tags=["cabs"])
app.include_router(alert_silences.router, tags=["alert_silences"])
app.include_router(audit_log.router, tags=["audit_log"])


@app.get("/health")
async def health():
    return {"status": "ok"}
