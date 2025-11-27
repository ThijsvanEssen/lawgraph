from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from lawgraph.api.routes import articles, judgments, nodes

app = FastAPI(
    title="Lawgraph API",
    version="0.3.0",
    description=(
        "Lawgraph biedt een FastAPI-laag boven de ArangoDB knowledge graph. "
        "De service exposeert endpoints om instrumentartikelen, uitspraken en knooppunten "
        "te verkennen met hun relaties."
    ),
)

app.include_router(articles.router, prefix="/api/articles", tags=["articles"])
app.include_router(judgments.router, prefix="/api/judgments", tags=["judgments"])
app.include_router(nodes.router, prefix="/api/nodes", tags=["nodes"])


# TOEGESTANE ORIGINS (dev)
origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,  # in dev: dit lijstje
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", tags=["root"])
async def root() -> dict[str, str]:
    """Basic service descriptor used by deployments."""
    return {"name": "lawgraph-api", "version": app.version}
