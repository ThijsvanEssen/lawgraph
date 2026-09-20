"""DTO definitions for the FastAPI layer, one module per API domain.

DTO definitions for the FastAPI layer.

Conventions across the API
--------------------------
* Every DTO has ``model_config = ConfigDict(extra="forbid")``. Unknown
  fields in inputs/outputs raise validation errors so contract drift
  surfaces immediately instead of being silently tolerated.
* Node-id references always use ``id`` (the Arango ``_id``,
  ``collection/key``) and ``key`` (the Arango ``_key``). Never
  ``article_id``/``dossier_id`` etc. — readers can split ``id`` if they
  need the collection prefix.
* Edges use ``from``/``to`` (matching the Arango edge shape and the
  graph-rendering convention).
* List responses expose two fields: ``items`` (the page, after ``limit``
  /``offset``) and ``total`` (the **absolute** count of matches,
  independent of ``limit`` — for "+N more" badges and pagination).
* Bulk endpoints return ``response_class=JSONResponse`` only when the
  payload is a free-form map (``dict[str, int]``: heat counts, in-flux
  counts). Every other response is a typed Pydantic model.

Import from the domain module, e.g.
``from lawgraph.api.schemas.instruments import InstrumentListResponse``.
Shared building blocks live in ``common``.
"""
