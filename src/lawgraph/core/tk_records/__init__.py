"""Readers for Tweede Kamer OData records: one payload in, node props out, a module per kind
of record.

The field names read here (``Voortouwcommissie_Id``, ``Agendapunt``, ``FractieGrootte``)
are the TK API's own. Everything the readers return is graph vocabulary: a node key plus a
props mapping, ready to wrap in a ``Node``. A reader takes a record the Kamer did not
delete: the normalizers set those apart first (``pipelines/normalize/_tk_deleted``).

Nothing in this package touches the database, so every reader is unit-testable against a
single recorded payload.
"""
