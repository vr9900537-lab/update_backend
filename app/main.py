import asyncio
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI

from app.api.v1.router import router as api_v1_router
from app.config import get_settings
from app.exceptions import register_exception_handlers
from app.middleware.request_context import RequestContextMiddleware
from app.workers.offline_devices import run_offline_device_worker

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    worker: asyncio.Task[None] | None = None
    if settings.offline_device_worker_enabled:
        worker = asyncio.create_task(
            run_offline_device_worker(), name="offline-device-worker"
        )
    try:
        yield
    finally:
        if worker is not None:
            worker.cancel()
            try:
                await worker
            except asyncio.CancelledError:
                pass


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description=(
        "Custody-band monitoring backend with Firebase Authentication and "
        "Firestore-backed user profiles. Real C05 device integration is not configured."
    ),
    lifespan=lifespan,
)
app.add_middleware(RequestContextMiddleware)
register_exception_handlers(app)
app.include_router(api_v1_router, prefix=settings.api_v1_prefix)
