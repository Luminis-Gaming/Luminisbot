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


async def probe_ranking_variants(session, token, report_code, fight_id, metric):
    """Try every combination of rankings() args to see if any of them return wipe data."""
    player_metric = "dps" if metric == "dps" else "hps"
    variants = [
        "compare: Parses",
        "compare: Rankings",
        "timeframe: Historical",
        "timeframe: Today",
        "compare: Parses, timeframe: Historical",
    ]
    headers = {'Authorization': f'Bearer {token}'}
    url = "https://www.warcraftlogs.com/api/v2/client"

    for extra in variants:
        query = f"""
        query($reportCode: String!, $fightIDs: [Int]!, $playerMetric: ReportRankingMetricType!) {{
          reportData {{
            report(code: $reportCode) {{
              rankings(fightIDs: $fightIDs, playerMetric: $playerMetric, {extra})
            }}
          }}
        }}
        """
        variables = {"reportCode": report_code, "fightIDs": [fight_id], "playerMetric": player_metric}
        async with session.post(url, json={'query': query, 'variables': variables}, headers=headers) as resp:
            body = await resp.json()
        if 'errors' in body:
            print(f"  [{extra}] -> GraphQL error: {body['errors'][0].get('message')}")
            continue
        rankings = body.get('data', {}).get('reportData', {}).get('report', {}).get('rankings')
        ranked = rankings.get('data') if isinstance(rankings, dict) else rankings
        count = len(ranked) if isinstance(ranked, list) else 0
        print(f"  [{extra}] -> {count} entries")
        if count:
            print(f"      raw: {json.dumps(ranked[0])[:600]}")


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
            print("  rankings empty with default args - probing variations for wipe support")
            print(f"  raw rankings: {json.dumps(rankings)[:400]}")
            await probe_ranking_variants(session, token, report_code, fight_id, metric)
            return

        record = ranked[0]
        print(f"  top-level keys: {list(record.keys())}")
        for role_name, role_data in (record.get('roles') or {}).items():
            for char in role_data.get('characters', []):
                print(f"  [{role_name:>7}] {char.get('name'):<16} "
                      f"parse={char.get('rankPercent')} ilvl={char.get('bracketPercent')}")


asyncio.run(main())
