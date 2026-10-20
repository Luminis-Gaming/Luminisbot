"""
The auction house collector as its own process - its own container (docker-compose.yml: ah-worker), so
downloading and parsing ~570 MB of auction data an hour never slows the bot or the web pages:

    python -m auctionhouse.worker

Every CHECK_MINUTES it runs collector.run_once(): each realm group is asked for a newer dump (an unchanged one costs
a 304), what changed is stored, and the item summaries the /ah pages read are recomputed. Stops cleanly on SIGTERM
(docker stop) between steps.
"""
import asyncio
import logging
import signal
import time

from . import CHECK_MINUTES, collector, db

logger = logging.getLogger('auctionhouse.worker')

SCHEMA_ATTEMPTS = 30


def ensure_schema():
    """The tables, created if missing (the bot's migrations make them too). Retries while Postgres is starting."""
    for attempt in range(1, SCHEMA_ATTEMPTS + 1):
        try:
            with db.transaction() as cur:
                db.ensure_schema(cur)
            return
        except Exception as e:
            if attempt == SCHEMA_ATTEMPTS:
                raise
            logger.warning(f'[AH] Database not ready ({e.__class__.__name__}: {e}); retrying in 10s')
            time.sleep(10)


async def main():
    await asyncio.to_thread(ensure_schema)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError):  # Windows: Ctrl+C still ends it
            pass
    logger.info(f'[AH] Auction house worker started: checking every realm every {CHECK_MINUTES} minutes')
    while not stop.is_set():
        started = loop.time()
        try:
            await collector.run_once()
        except Exception:
            logger.exception('[AH] Collection failed')
        wait = max(30.0, CHECK_MINUTES * 60 - (loop.time() - started))
        try:
            await asyncio.wait_for(stop.wait(), timeout=wait)
        except asyncio.TimeoutError:
            pass
    logger.info('[AH] Auction house worker stopped')


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    asyncio.run(main())
