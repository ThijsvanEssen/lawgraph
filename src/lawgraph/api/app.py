from __future__ import annotations

from fastapi import FastAPI

from lawgraph.api.routes import articles, judgments, nodes

app = FastAPI(title="Lawgraph API")

app.include_router(articles.router, prefix="/api/articles", tags=["articles"])
app.include_router(judgments.router, prefix="/api/judgments", tags=["judgments"])
app.include_router(nodes.router, prefix="/api/nodes", tags=["nodes"])


@app.get("/", tags=["root"])
async def root() -> dict[str, str]:
    """Basic service descriptor used by deployments."""
    return {"name": "lawgraph-api", "version": "0.1.0"}
