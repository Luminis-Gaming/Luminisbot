"""
Build the matchmaking PlayerPool from raw signup rows.

Rows are plain dicts (RealDictCursor output or test fixtures) with keys:
    signup_id, discord_id, character_name, realm_slug, character_class,
    role, armor_type, signed_at, score, grace_points
Pure function — no DB access here.
"""
from ..models import Person, SignupOption


def build_pool(signup_rows) -> list:
    persons = {}
    first_signed = {}

    for row in signup_rows:
        pid = str(row['discord_id'])
        if pid not in persons:
            persons[pid] = Person(
                discord_id=pid,
                grace_points=int(row.get('grace_points') or 0),
                display_name=row.get('display_name') or '',
            )
        persons[pid].options.append(SignupOption(
            signup_id=row.get('signup_id') or 0,
            discord_id=pid,
            character_name=row['character_name'],
            realm_slug=row['realm_slug'],
            character_class=row['character_class'],
            role=row['role'],
            armor_type=row['armor_type'],
            score=float(row.get('score') or 0.0),
        ))
        signed_at = row.get('signed_at')
        if signed_at is not None:
            if pid not in first_signed or signed_at < first_signed[pid]:
                first_signed[pid] = signed_at

    # Rank persons by their earliest signup (0 = first to sign)
    ordered = sorted(persons, key=lambda pid: (first_signed.get(pid) is None,
                                               first_signed.get(pid), pid))
    for rank, pid in enumerate(ordered):
        persons[pid].signup_rank = rank

    return list(persons.values())
