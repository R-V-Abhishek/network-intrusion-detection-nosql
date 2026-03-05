"""API entry point for the Network Intrusion Detection System."""

from fastapi import FastAPI

from dashboard.api_analytics import router as analytics_router

app = FastAPI(title="Network Intrusion Detection API", version="0.1.0")

app.include_router(analytics_router)


@app.get("/health")
def health() -> dict[str, str]:
	"""Simple health endpoint for local checks and container probes."""
	return {"status": "ok"}
