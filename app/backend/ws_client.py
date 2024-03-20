from backend.data_processor import process_data_for_send
from backend.ws_processor import process_message
from nanows.api import NanoWebSocket
from backend.helpers import MessageCounter
from backend.elections import ElectionHandler
from backend.overview import OverviewHandler
from backend.cache_service import MemcacheCache
from asyncio import Lock, sleep as aio_sleep
from os import getenv

import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Quart")

WS_URL = getenv("WS_URL")
MEMCACHE_HOST = getenv("MEMCACHE_HOST")
MEMCACHE_PORT = getenv("MEMCACHE_PORT")


election_cache = MemcacheCache(
    host=MEMCACHE_HOST, port=MEMCACHE_PORT, prefix="el_")
overview_cache = MemcacheCache(
    host=MEMCACHE_HOST, port=MEMCACHE_PORT, prefix="ov_")

election_handler = ElectionHandler(election_cache)
overview_handler = OverviewHandler(overview_cache)

elections_temp = {}
election_results_lock = Lock()

current_hash = None


async def get_election_details(transaction_hash):
    return await election_cache.get(transaction_hash)


async def get_election_overview():
    # Slicing the first 100 confirmed and 250 unconfirmed elections for display
    processed_elections = await overview_handler.retrieve_election_data(
        num_confirmed=50, num_unconfirmed=100)

    return current_hash, processed_elections


async def aggregate_election_overview():
    global elections_temp, current_hash
    while True:
        async with election_results_lock:
            elections_delta = elections_temp
            elections_temp = {}

        updated_elections = await election_handler.merge_elections(elections_delta)

        # View Transformer
        processed_update_elections = await process_data_for_send(updated_elections)

        # View Aggregator
        if processed_update_elections:
            current_hash = await overview_handler.process_and_cache_elections(processed_update_elections)

        await aio_sleep(0.45)


async def run_nano_ws_listener():
    # This processes all the incoming websocket messages and puts them into elections_temp
    counter = MessageCounter(logger=logger)
    while True:
        try:
            # nano_ws = NanoWebSocket(url="wss://proxy.nanobrowse.com/ws")
            nano_ws = NanoWebSocket(url=WS_URL)
            await nano_ws.connect()
            # await nano_ws.subscribe_new_unconfirmed_block()
            await nano_ws.subscribe_vote()
            await nano_ws.subscribe_started_election()
            await nano_ws.subscribe_confirmation(include_block=False)
            await nano_ws.subscribe_stopped_election()

            async for message in nano_ws.receive_messages():
                counter.increment()
                async with election_results_lock:
                    await process_message(message, elections_temp)
        except Exception as exc:
            logging.warn(
                f"Websocket closed with Exception : {exc}\n Reconnecting...")
            # attemp reconnect after 1 second (while true)
            await aio_sleep(1)
