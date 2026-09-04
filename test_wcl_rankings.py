# test_wcl_rankings.py
# Quick check that the GraphQL rankings + bossPercentage fields return usable data.
# Usage: python test_wcl_rankings.py <report_code> <fight_id> [dps|hps]

import asyncio
import json
import sys

import aiohttp

from wcl_api import (
    get_wcl_token,
    get_fight_details,
    get_all_boss_health_for_report,
)


async def main():
    if len(sys.argv) < 3:
        print("Usage: python test_wcl_rankings.py <report_code> <fight_id> [dps|hps]")
        return

    report_code = sys.argv[1]
    fight_id = int(sys.argv[2])
    metric = sys.argv[3] if len(sys.argv) > 3 else "dps"

    async with aiohttp.ClientSession() as session:
        token = await get_wcl_token(session)
        if not token:
            print("Could not get a WCL token - check WCL_CLIENT_ID / WCL_CLIENT_SECRET")
            return

        print("\n=== boss health (wipes) ===")
        boss_health = await get_all_boss_health_for_report(session, token, report_code)
        for fid, pct in sorted(boss_health.items()):
            print(f"  fight {fid}: {pct:.2f}%")

        print("\n=== fight details ===")
        details = await get_fight_details(
            session, token, report_code, fight_id,
            encounter_id=1, difficulty=5, metric=metric, is_kill=True,
        )
        if not details:
            print("  no fight details returned")
            return

        rankings = details.get('rankings')
        ranked = rankings.get('data') if isinstance(rankings, dict) else rankings
        if not ranked:
            print("  rankings empty (expected for a wipe or unranked difficulty)")
            print(f"  raw rankings: {json.dumps(rankings)[:400]}")
            return

        record = ranked[0]
        print(f"  top-level keys: {list(record.keys())}")
        for role_name, role_data in (record.get('roles') or {}).items():
            for char in role_data.get('characters', []):
                print(f"  [{role_name:>7}] {char.get('name'):<16} "
                      f"parse={char.get('rankPercent')} ilvl={char.get('bracketPercent')}")


asyncio.run(main())
