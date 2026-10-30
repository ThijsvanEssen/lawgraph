"""Queries of ``normalize kst-sru``, the Kamerstukken of the Tweede Kamer from the KOOP SRU."""

from __future__ import annotations

from lawgraph.config.constants import COLLECTION_DOCUMENTS, SOURCE_KST, SOURCE_TK
from lawgraph.db.counting import Store


def kst_copies_of_tk_documents(store: Store) -> list[str]:
    """The keys of the papers of the SRU (``source`` ``kst``) the Tweede Kamer's API holds
    too: a document of ``source`` ``tk`` with the same dossier, suffix and number."""
    return [
        str(key)
        for key in store.query(
            f"""
            SELECT k.key
            FROM {COLLECTION_DOCUMENTS} k
            WHERE k.source = '{SOURCE_KST}'
              AND EXISTS (
                SELECT 1 FROM {COLLECTION_DOCUMENTS} t
                WHERE t.dossier_number = k.dossier_number
                  AND t.source = '{SOURCE_TK}'
                  AND coalesce(lg_str(t.props -> 'dossier_suffix'), '')
                      = coalesce(lg_str(k.props -> 'dossier_suffix'), '')
                  AND t.props ->> 'sequence' = k.props ->> 'sequence'
              )
            ORDER BY k.key
            """
        )
    ]
