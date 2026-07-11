from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Placeholder: DB/cache/vector-store connection startup and shutdown
    # are wired here once the DB connections sub-sprint lands.
    yield
