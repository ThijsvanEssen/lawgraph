"""DTO definitions for the FastAPI layer, one module per API domain.

Conventions across the API
--------------------------
* Every DTO derives from ``common.StrictModel`` (``extra="forbid"``). Unknown
  fields in inputs/outputs raise validation errors so contract drift
  surfaces immediately instead of being silently tolerated.
* Node-id references always use ``id`` (the node id,
  ``collection/key``) and ``key`` (the id without its collection). Never
  ``article_id``/``dossier_id`` etc. — readers can split ``id`` if they
  need the collection prefix.
* Edges use ``from``/``to`` (the graph-rendering convention).
* A day is ``<verb>_on`` (``published_on``), a moment ``<verb>_at`` and a period
  ``from_date``/``to_date``, both inclusive. ``valid_from``/``valid_until`` (half-open
  versions) and ``observed_from``/``observed_until`` (snapshots) are other notions.
  ``tests/api/test_field_names.py`` lists the fields that do not follow yet.
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
