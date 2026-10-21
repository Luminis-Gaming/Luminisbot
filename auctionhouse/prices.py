"""
Prices that mean something: which listings to leave out, and an item's numbers across EU.

An auction house shows asks, not sales, and a lot of asks are noise:
  - a price wall: one seller or bot posting the item on many realms at the same odd price (6,255,261g), or a few
    gold apart per realm (4,018,233g / 4,021,863g). People pick prices like 3,499,999g, 296,000g or 50,000g (three
    significant digits or fewer, maybe minus 1g), or undercut such a price by a few gold (2,899,974g under
    2,900,000g - at most 0.01%); a cluster of other prices is a wall. Found per item over every roll at once - one roll on a few
    realms is too little to see the pattern.
  - at the cap: 9,999,999g is the most an auction can ask. People post things there as a lottery ticket; it says
    nothing about what the item is worth.
  - far above: over 10x the typical price (the lower quartile of the other realms).
Both stay visible on the pages but are left out of medians, rankings and gaps. The same rules run in the browser
(web/assets.py) for the item page.

Pure functions: no database (tests/test_auctionhouse.py).
"""
import math

GAP_MIN_REALMS = 8        # a roll needs this many real prices before we suggest a gap
CLUSTER = 1.003          # prices within 0.3% of their neighbour form one cluster
WALL_MIN = 3             # an odd-priced cluster this big is a wall
FAR_ABOVE = 10           # x the typical price
AH_CUT = 0.95            # the auction house keeps 5%
PRICE_CAP = 9_990_000 * 10000  # at or near the 9,999,999g maximum: a lottery ticket, not a price
MARKET_SHARE = 0.15      # a commodity's market price: the average of the cheapest 15% of its supply


def _sig_digits(n):
    return len(str(n).rstrip('0'))


def is_round(copper):
    g = round(copper / 10000)
    return g < 1000 or _sig_digits(g) <= 3 or _sig_digits(g + 1) <= 3


def anchored(copper):
    """
    A few gold under a two-significant-digit price: people undercutting a common price (2,899,974g under 2,900,000g).
    A bot a few thousand gold under (3,596,867g under 3,600,000g) isn't.
    """
    g = copper / 10000
    if g <= 0:
        return True
    step = 10 ** (math.floor(math.log10(g)) - 1)
    anchor = math.ceil(g / step) * step
    return 0 <= anchor - g <= max(anchor * 0.0001, 1)


def quantile(sorted_values, p):
    if not sorted_values:
        return None
    i = (len(sorted_values) - 1) * p
    lo, hi = math.floor(i), math.ceil(i)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (i - lo)


def find_walls(prices):
    """
    prices: every (roll, realm) cheapest price of one item. -> {price: how often it was seen} for the wall prices.
    """
    seen = {}
    for p in prices:
        seen[p] = seen.get(p, 0) + 1
    walls = {}
    cluster = []

    def close():
        count = sum(seen[p] for p in cluster)
        odd = sum(seen[p] for p in cluster if not (is_round(p) or anchored(p)))
        if count >= WALL_MIN and odd * 2 >= count:
            for p in cluster:
                walls[p] = count
        cluster.clear()

    for p in sorted(seen):
        if cluster and p > cluster[-1] * CLUSTER:
            close()
        cluster.append(p)
    if cluster:
        close()
    for p, c in seen.items():
        if p >= PRICE_CAP:
            walls[p] = c
    return walls


def commodity_stats(levels):
    """
    One commodity's numbers from its price ladder: [(unit price, quantity)], cheapest first. Stackable goods sell on
    one auction house for the whole region, so there are no realms to compare - what matters is how much you pay
    for how many. The market price is the average unit price of the cheapest 15% of the supply (what a reasonable
    purchase costs, not the one cheapest unit); p05 / p30 are the unit prices 5% and 30% of the way into the supply.
    Asks at the price cap are left out. None when nothing real is listed.
    """
    levels = [(p, q) for p, q in levels if p < PRICE_CAP and q > 0]
    total = sum(q for _, q in levels)
    if not total:
        return None

    def price_at(fraction):
        need, seen = max(1, fraction * total), 0
        for p, q in levels:
            seen += q
            if seen >= need:
                return p
        return levels[-1][0]

    want, cost, got = max(1, round(total * MARKET_SHARE)), 0, 0
    for p, q in levels:
        take = min(q, want - got)
        cost += take * p
        got += take
        if got >= want:
            break
    return {'lo': levels[0][0], 'p05': price_at(0.05), 'market': round(cost / got), 'p30': price_at(0.30),
            'quantity': total, 'levels': len(levels)}


def typical_price(realm_lows, walls):
    """The lower quartile of the realms' cheapest prices that aren't walls (None without any)."""
    clean = sorted(p for p in realm_lows if p not in walls)
    return quantile(clean, 0.25)


def stats(realm_rows, walls, reference=None):
    """
    realm_rows: [(realm, cheapest price, listings)] - one per realm. -> the item's (or roll's) numbers over the
    realms whose cheapest price is real, or None when there's nothing. reference: the item's typical price, used
    when there are too few realms here to tell what typical is.
    """
    rows = sorted(realm_rows, key=lambda r: r[1])
    if not rows:
        return None
    rest = [r for r in rows if r[1] not in walls]
    typical = quantile([r[1] for r in rest], 0.25) if len(rest) >= 5 else reference
    sane = [r for r in rest if typical is None or r[1] <= typical * FAR_ABOVE]
    fell_back = not sane
    if fell_back:
        sane = rows
    lows = [r[1] for r in sane]
    # the gap's sell side: a typical realm (the median), not the priciest - asks above it often never sell
    median = quantile(lows, 0.5)
    target = min(sane, key=lambda r: abs(r[1] - median))
    return {
        'realms': len(rows), 'listings': sum(r[2] for r in rows),
        'lo': rows[0][1], 'lo_realm': rows[0][0],
        'hi': sane[-1][1], 'hi_realm': sane[-1][0],
        'p25': round(quantile(lows, 0.25)), 'med': round(quantile(lows, 0.5)), 'p75': round(quantile(lows, 0.75)),
        'flagged': 0 if fell_back else len(rows) - len(sane), 'fell_back': fell_back, 'sane': len(sane),
        'target': target[1], 'target_realm': target[0],
        'gain': round(target[1] * AH_CUT - rows[0][1]),
    }
