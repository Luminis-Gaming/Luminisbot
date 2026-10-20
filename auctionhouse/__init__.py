"""
Auction house browser - every EU realm's auction house, compared.

Search every item on sale in EU with the filters players expect (item level, required level, rarity, expansion,
category, secondary and tertiary stats, socket, below vendor price), then open an item to see where it sells for
the most and the least, each stat roll's price, every listing on your realm and the price history.

Two halves, in two containers:
  - the collector (worker.py, collector.py) runs on its own - docker-compose.yml's ah-worker service,
    `python -m auctionhouse.worker` - so its downloading and parsing never slow the bot or the pages;
  - the public pages at /ah (web/) are served by the bot's web server and only read the database.
Data from Blizzard's auction API; item details from the game's own tables (gamedata.py); tooltips from Wowhead
through raidanalysis.items.

Integration (matching the house patterns): auctionhouse.db.ensure_schema(cursor) inside run_migrations(), and
auctionhouse.web.register_routes(app) inside oauth_server.create_app().
"""
CHECK_MINUTES = 10  # how often every realm is asked for a newer dump (each changes about hourly)
