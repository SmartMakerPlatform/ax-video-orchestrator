from fastapi import FastAPI

from app.jobs import router as jobs_router

app = FastAPI()
app.include_router(jobs_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
