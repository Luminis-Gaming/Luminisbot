"""
Mythic+ matchmaking engine — pure Python, no discord/psycopg2 imports.

Public API:
    build_pool(rows)                 -> list[Person]
    build_roster(persons, seed)      -> Roster
    compute_grace_changes(roster, persons_by_id) -> GraceChanges
    alternate_reason(person, roster, persons_by_id) -> str
    roster_score(groups, persons_by_id) -> tuple
"""
from .grace import GraceChanges, alternate_reason, compute_grace_changes
from .pool import build_pool
from .scoring import roster_score
from .solver import build_roster

__all__ = [
    'GraceChanges',
    'alternate_reason',
    'build_pool',
    'build_roster',
    'compute_grace_changes',
    'roster_score',
]
