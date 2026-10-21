"""
Estimated sales. Blizzard shows listings, never sales - but a listing that's gone at the next snapshot (about an
hour later) while it still had hours to run was either bought or cancelled by its seller. Nothing in the data says
which, so these are estimates ("about this many sold"), and deliberately cautious ones, because sellers and their
bots cancel and repost all day:

  - buyers take the cheapest first. A listing that vanished while a cheaper one of the same roll (or a cheaper
    commodity stack) stayed up, untouched, was cancelled - the Bound Serpent's Jade Eyes "sold" at three times
    their realm's cheapest were sellers clearing out stale asks
  - a listing that vanished as a new one of the same roll appeared just under it was reposted, not bought (an
    undercutting bot's hourly routine)
  - only listings with time left LONG (2-12 h) or VERY_LONG count: a SHORT or MEDIUM one may simply have run out
  - nothing is counted across a gap of more than MAX_GAP_HOURS between two snapshots of the same auction house
  - a commodity stack that got smaller was partly bought: the difference counts, whatever its time left
  - asks that never were real prices aren't counted when they vanish: bot price walls, the price cap, far above
    the typical price (prices.py)

Pure functions: no database (tests/test_auctionhouse.py). collector.py stores what they find in ah_sales and
ah_commodity_sales.
"""
from .prices import FAR_ABOVE, PRICE_CAP

LONG = 2                 # TIME_LEFT code of LONG (collector.TIME_LEFT)
MAX_GAP_HOURS = 3
COMMODITY_FAR_ABOVE = 3  # a vanished commodity stack over 3x the market price: more likely cancelled than bought
REPOST_UNDER = 0.95      # a new listing of the same roll at 95-100% of a vanished one's price: the same seller's repost


def realm_sales(previous, current, walls, typical):
    """
    previous: one realm's listings at the last snapshot, [(auction_id, item_id, variant_id, price, time_left)];
    current: this snapshot's, {auction_id: (variant_id, price)}. walls: item -> set of wall prices;
    typical: item -> typical price.
    -> {(item_id, variant_id): [sold, revenue]}
    """
    rolls = {}
    for listing in previous:
        rolls.setdefault((listing[1], listing[2]), []).append(listing)
    before = {listing[0] for listing in previous}
    posted = {}
    for auction_id, (variant_id, price) in current.items():
        if auction_id not in before:
            posted.setdefault(variant_id, []).append(price)
    out = {}
    for (item_id, variant_id), listings in rolls.items():
        still_up = [price for auction_id, _, _, price, _ in listings if auction_id in current]
        cheapest_left = min(still_up) if still_up else None
        reposts = sorted(posted.get(variant_id, ()))
        usual = typical.get(item_id)
        for auction_id, _, _, price, time_left in sorted(listings, key=lambda listing: listing[3]):
            if auction_id in current or time_left < LONG or price >= PRICE_CAP:
                continue
            if price in walls.get(item_id, ()) or (usual and price > usual * FAR_ABOVE):
                continue
            if cheapest_left is not None and price > cheapest_left:
                continue  # a cheaper one of the same roll is still there: nobody bought past it
            repost = next((i for i, p in enumerate(reposts) if price * REPOST_UNDER <= p <= price), None)
            if repost is not None:
                del reposts[repost]
                continue
            count = out.setdefault((item_id, variant_id), [0, 0])
            count[0] += 1
            count[1] += price
    return out


def commodity_sales(previous, current, market):
    """
    previous: the region's commodity auctions at the last snapshot, {auction_id: (item_id, unit_price, quantity,
    time_left)}; current: {auction_id: quantity} now; market: item -> market price.
    -> {item_id: [units sold, revenue]}
    """
    untouched = {}  # item -> the cheapest stack still up with nothing bought from it: nobody bought anything dearer
    for auction_id, (item_id, price, quantity, _) in previous.items():
        if current.get(auction_id) == quantity and price < untouched.get(item_id, PRICE_CAP):
            untouched[item_id] = price
    out = {}
    for auction_id, (item_id, price, quantity, time_left) in previous.items():
        now = current.get(auction_id)
        if now is not None:
            units = quantity - now if now < quantity else 0   # partly bought: certainly a sale
        elif time_left >= LONG and price < PRICE_CAP and price <= untouched.get(item_id, PRICE_CAP):
            usual = market.get(item_id)
            units = 0 if usual and price > usual * COMMODITY_FAR_ABOVE else quantity
        else:
            units = 0
        if units > 0:
            count = out.setdefault(item_id, [0, 0])
            count[0] += units
            count[1] += units * price
    return out
