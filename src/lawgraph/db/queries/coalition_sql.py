"""What the coalition did on a vote, as SQL on a row of ``lg_decision_coalition`` (kept by
``semantic tk-coalition-votes``): the same fields wherever a vote is shown (the list and the
detail of decisions, the feed, a member's votes, a dossier's timeline)."""

from __future__ import annotations


def coalition_object(row: str) -> str:
    """SQL: what the coalition did on a vote, from the row *row* of ``lg_decision_coalition``
    (null without one)."""
    return f"""CASE WHEN {row}.id IS NULL THEN NULL ELSE json_build_object(
        'cabinet', {row}.cabinet,
        'coalition_for', {row}.coalition_for,
        'coalition_against', {row}.coalition_against,
        'opposition_for', {row}.opposition_for,
        'opposition_against', {row}.opposition_against,
        'pattern', {row}.pattern,
        'carried', {row}.carried,
        'decisive', {row}.decisive
    ) END"""


def coalition_factions(row: str) -> str:
    """SQL: each coalition faction's choice on a vote, from the row *row* of
    ``lg_decision_coalition``, ``[{key, short, choice, seats_for, seats_against}]`` in the order kept
    (most seats first); ``[]`` without one. ``short`` is the faction's abbreviation, else
    its name."""
    return f"""(
        SELECT coalesce(json_agg(json_build_object(
            'key', x.f -> 'key',
            'short', (SELECT coalesce(lg_str(fa.props -> 'abbreviation'),
                                      lg_str(fa.props -> 'name'))
                      FROM factions fa WHERE fa.key = x.f ->> 'key'),
            'choice', x.f -> 'choice',
            'seats_for', x.f -> 'seats_for',
            'seats_against', x.f -> 'seats_against'
        ) ORDER BY x.n), '[]'::json)
        FROM json_array_elements(coalesce({row}.factions, '[]'::json))
            WITH ORDINALITY AS x(f, n)
    )"""
