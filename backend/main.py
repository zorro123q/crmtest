"""
FastAPI application entrypoint.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import OperationalError, SQLAlchemyError

from app.api.routes import admin, ai, auth, card_evaluations, leads, opportunities, opportunity_report, scoring
from app.api.routes.analytics import router as analytics_router
from app.core.config import settings
from app.core.security import hash_password
from app.db.session import AsyncSessionLocal, engine
from app.models import User
from app.services.schema_service import ensure_runtime_schema


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await ensure_runtime_schema()
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(User.id).where(User.username == "admin"))
            existing_admin_id = result.scalar_one_or_none()

            if existing_admin_id is None:
                # 默认密码从环境变量 ADMIN_DEFAULT_PASSWORD 读取，避免硬编码弱密码
                default_pwd = settings.ADMIN_DEFAULT_PASSWORD
                session.add(User(username="admin", password=hash_password(default_pwd)))
                await session.commit()
    except SQLAlchemyError:
        # If the schema has not been created yet, do not block app startup.
        pass

    yield

    await engine.dispose()


app = FastAPI(
    title=settings.APP_NAME,
    description="AI-driven metadata CRM",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    lifespan=lifespan,
)

app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(leads.router)
app.include_router(opportunities.router)
app.include_router(opportunity_report.router)
app.include_router(scoring.router)
app.include_router(ai.router)
app.include_router(card_evaluations.router)
app.include_router(admin.router)
app.include_router(analytics_router)


def _database_error_detail(exc: OperationalError) -> str:
    origin = getattr(exc, "orig", None)
    args = getattr(origin, "args", ())
    code = args[0] if args else None

    if code == 1045:
        return (
            "Database authentication failed. Check DATABASE_URL / DATABASE_SYNC_URL in backend/.env "
            "and verify the MySQL user credentials."
        )
    if code == 1049:
        return (
            "Database 'salespilot_db' does not exist. Create it first, then run the SQL files "
            "under backend/migrations."
        )
    if code == 1054:
        return (
            "The database schema is behind the current code. Missing columns were detected in "
            "the leads or opportunities tables. Run backend/migrations/004_add_scoring_and_archive_support.sql."
        )
    if code in {2003, 2005}:
        return "Cannot connect to MySQL. Check that the service is running and the host/port settings are correct."
    return "Database is temporarily unavailable. Check MySQL status and backend/.env settings."


@app.exception_handler(OperationalError)
async def handle_database_operational_error(_: Request, exc: OperationalError):
    return JSONResponse(status_code=503, content={"detail": _database_error_detail(exc)})


@app.get("/api/health")
async def health():
    return {"status": "ok", "app": settings.APP_NAME, "env": settings.APP_ENV}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)