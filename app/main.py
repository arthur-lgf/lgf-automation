from fastapi import FastAPI

from app.routers import snapshots


def create_app() -> FastAPI:
    app = FastAPI(
        title="lgf-automation",
        version="0.1.0",
        description="Google Sheets snapshot service.",
    )
    app.include_router(snapshots.router)

    @app.get("/healthz", tags=["meta"])
    def healthz() -> dict:
        return {"ok": True}

    return app


app = create_app()
