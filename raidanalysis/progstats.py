"""
Mythic pull counts across guilds, from progstats.io (https://progstats.io).

progstats.io tracks how many pulls every guild needed to kill each Mythic boss
(it has no Heroic data). It has no official API - we read the same public
GraphQL endpoint its own site uses, cache each boss for a day (so roughly one
request per boss per day) and credit it wherever the numbers are shown.
"""
import logging
import time

import aiohttp

logger = logging.getLogger(__name__)

URL = 'https://progstats.io/graphql'
CACHE_SECONDS = 86400
ERROR_CACHE_SECONDS = 3600
MYTHIC = 5

_cache = {}  # encounter_id -> (fetched_at, stats or None)

QUERY = """
query PullStats($encounterId: Int!, $difficulty: Int!) {
  encounterStatSummaryV2(encounterId: $encounterId, difficulty: $difficulty) { killCount pullsRange }
  encounterStatOverviewV2(encounterId: $encounterId, difficulty: $difficulty) {
    __typename
    ... on ColumnarBins { metricType binStart binEnd count }
  }
}
"""


def _quantile(bins, q):
    """Approximate quantile from (start, end, count) bins, interpolating inside the bin."""
    total = sum(c for _, _, c in bins)
    if not total:
        return None
    target, seen = q * total, 0
    for start, end, count in bins:
        if count and seen + count >= target:
            return start + (end - start) * (target - seen) / count
        seen += count
    return bins[-1][1]


def share_needing_more(bins, pulls):
    """Share of killing guilds that needed more pulls than `pulls`."""
    total = sum(c for _, _, c in bins)
    if not total:
        return None
    more = 0.0
    for start, end, count in bins:
        if pulls < start:
            more += count
        elif start <= pulls < end:
            more += count * (end - pulls) / (end - start)
    return more / total


def parse(payload):
    data = payload.get('data') or {}
    summary = data.get('encounterStatSummaryV2') or {}
    overview = data.get('encounterStatOverviewV2') or {}
    grouped = {}
    for metric, start, end, count in zip(overview.get('metricType') or [], overview.get('binStart') or [],
                                         overview.get('binEnd') or [], overview.get('count') or []):
        if metric == 'PULL_COUNT':  # one row per bin per day - fold the days together
            key = (round(start, 3), round(end, 3))
            grouped[key] = grouped.get(key, 0) + (count or 0)
    bins = [(start, end, count) for (start, end), count in sorted(grouped.items())]
    if not summary.get('killCount') or not bins:
        return None
    return {'kills': summary['killCount'], 'bins': bins,
            'p25': _quantile(bins, 0.25), 'median': _quantile(bins, 0.5), 'p75': _quantile(bins, 0.75)}


async def mythic_pull_stats(encounter_id):
    """{'kills', 'bins', 'p25', 'median', 'p75'} for a Mythic boss, or None (no data / site unreachable)."""
    cached = _cache.get(encounter_id)
    if cached and time.time() - cached[0] < (CACHE_SECONDS if cached[1] else ERROR_CACHE_SECONDS):
        return cached[1]
    stats = None
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(URL, json={'query': QUERY, 'variables': {'encounterId': encounter_id,
                                                                            'difficulty': MYTHIC}},
                                    headers={'User-Agent': 'LuminisBot raid analysis (guild tool)'},
                                    timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 200:
                    stats = parse(await resp.json(content_type=None))
                else:
                    logger.warning(f"[RAIDS] progstats.io returned {resp.status} for {encounter_id}")
    except Exception as e:
        logger.warning(f"[RAIDS] progstats.io lookup failed for {encounter_id}: {e}")
    _cache[encounter_id] = (time.time(), stats)
    return stats
