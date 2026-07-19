from contextlib import asynccontextmanager

from fastapi import FastAPI

from . import db, gitea
from .routers import activity, admin, auth, drafts, prompts, pulls


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    yield
    await gitea.close_client()


app = FastAPI(title="Prompt Library", docs_url=None, redoc_url=None, openapi_url=None,
              lifespan=lifespan)


@app.get("/healthz")
async def healthz():
    return {"ok": True}


app.include_router(auth.router)
app.include_router(prompts.router)
app.include_router(drafts.router)
app.include_router(pulls.router)
app.include_router(activity.router)
app.include_router(admin.router)
