"""SQL: a judgment as the lists of other nodes show it, read from the columns of its row
(``pj_*``) and the row of ``lg_judgment_light``, never from its props (a judgment is its
text)."""

from __future__ import annotations

from lawgraph.db.queries.judgment_light import outcome_pairs


def slim_judgment(row: str, *pairs: str) -> str:
    """SQL: the judgment *row* as a link to it, ``{id, key, props: {display_name, ecli}}``,
    then the json_build_object *pairs* (``'meta', e.doc -> 'meta'``)."""
    more = "".join(f", {pair}" for pair in pairs)
    return f"""json_build_object(
            'id', {row}.id,
            'key', {row}.key,
            'props', json_build_object(
                'display_name', {row}.pj_display_name, 'ecli', {row}.pj_ecli
            ){more}
        )"""


def listed_judgment(row: str, light: str, *pairs: str) -> str:
    """SQL: the judgment *row* as a row of a list of judgments,
    ``{id, key, props: {ecli, display_name, court_code, tier, court_kind, date_eff, …}}``:
    then the json_build_object *pairs* of the list, then how it ended (``outcome_pairs``),
    from its row *light* of ``lg_judgment_light``."""
    more = "".join(f"{pair}, " for pair in pairs)
    return f"""json_build_object(
            'id', {row}.id,
            'key', {row}.key,
            'props', json_build_object(
                'ecli', {row}.pj_ecli, 'display_name', {row}.pj_display_name,
                'court_code', {row}.pj_court_code, 'tier', {row}.pj_tier,
                'court_kind', {row}.pj_court_kind, 'date_eff', {row}.pj_date_eff,
                {more}{outcome_pairs(f"{light}.props")}
            )
        )"""
