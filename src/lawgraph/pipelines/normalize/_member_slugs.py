"""Give every member without one a slug (``core.member_slugs``): after each pipeline that
writes members (the Tweede Kamer, Rijksoverheid, the Eerste Kamer), one rule for all."""

from __future__ import annotations

from lawgraph.config.constants import COLLECTION_MEMBERS
from lawgraph.core.logging import get_logger
from lawgraph.core.member_slugs import new_slugs
from lawgraph.core.models import Node, NodeType
from lawgraph.db import NodeWriter
from lawgraph.db.counting import Store
from lawgraph.db.queries.normalize import tk as normalize_tk

logger = get_logger(__name__)


def assign_member_slugs(store: Store) -> int:
    """Write the slug of every member that has a name and no slug yet; the number."""
    found = new_slugs(normalize_tk.member_slug_rows(store))
    with NodeWriter(store) as writer:
        writer.add_all(
            Node(
                collection=COLLECTION_MEMBERS,
                type=NodeType.MEMBER,
                key=key,
                labels=[],
                props={"slug": slug},
            )
            for key, slug in found.items()
        )
    logger.info("Gave %d members a slug.", len(found))
    return len(found)
