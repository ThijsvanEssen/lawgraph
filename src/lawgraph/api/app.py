from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from lawgraph.api.routes import articles, judgments, nodes
from lawgraph.api.routes.commissies import leden_router
from lawgraph.api.routes.commissies import router as commissies_router
from lawgraph.api.routes.dossiers import party_router
from lawgraph.api.routes.dossiers import router as dossiers_router
from lawgraph.api.routes.search import router as search_router

app = FastAPI(
    title="Lawgraph API",
    version="0.4.0",
    description=(
        "Lawgraph biedt een FastAPI-laag boven de ArangoDB knowledge graph. "
        "De service exposeert endpoints voor wetsartikelen, uitspraken, "
        "parlementaire dossiers en wetgevingsgeschiedenis."
    ),
)

app.include_router(articles.router, prefix="/api/articles", tags=["articles"])
app.include_router(judgments.router, prefix="/api/judgments", tags=["judgments"])
app.include_router(nodes.router, prefix="/api/nodes", tags=["nodes"])
app.include_router(dossiers_router, prefix="/api/dossiers", tags=["dossiers"])
app.include_router(commissies_router, prefix="/api/commissies", tags=["commissies"])
app.include_router(leden_router, prefix="/api/leden", tags=["leden"])
app.include_router(party_router, prefix="/api/partijen", tags=["partijen"])
app.include_router(search_router, prefix="/api/search", tags=["search"])

origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:5174",
    "http://127.0.0.1:5174",
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
