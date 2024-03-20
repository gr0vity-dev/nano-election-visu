from backend.data_processor import process_data_for_send, update_overview_data
from backend.ws_processor import process_message
from nanows.api import NanoWebSocket
from asyncio import Lock, sleep as aio_sleep
from backend.elections import ElectionHandler
from backend.cache_service import MemcacheCache
import logging
from os import getenv
from copy import deepcopy


WS_URL = getenv("WS_URL")
MEMCACHE_HOST = getenv("MEMCACHE_HOST")
MEMCACHE_PORT = getenv("MEMCACHE_PORT")
msg_count = 0

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Quart")

election_cache = MemcacheCache(host=MEMCACHE_HOST, port=MEMCACHE_PORT)
election_handler = ElectionHandler(election_cache)


elections_temp = {}
election_results_lock = Lock()
confirmed_elections = {}
unconfirmed_elections = {}
current_hash = None
election_delta = {}


async def get_election_results(transaction_hash):
    return await election_cache.get(transaction_hash)


def get_processed_elections():
    # Slicing the first 100 confirmed and 250 unconfirmed elections for display
    confirmed_display = dict(list(confirmed_elections.items())[:100])
    unconfirmed_display = dict(list(unconfirmed_elections.items())[:250])
    return current_hash, {**confirmed_display, **unconfirmed_display}


async def trim_election_results():
    global election_delta, elections_temp, current_hash, confirmed_elections, unconfirmed_elections
    while True:
        async with election_results_lock:
            elections_delta = elections_temp
            elections_temp = {}

        updated_elections = await election_handler.merge_elections(elections_delta)

        # View Transformer
        processed_update_elections = await process_data_for_send(updated_elections)

        # View Aggregator
        if processed_update_elections:
            processed_l = {**confirmed_elections, **unconfirmed_elections}
            current_hash, confirmed_elections, unconfirmed_elections = update_overview_data(
                processed_l, processed_update_elections)

        await aio_sleep(0.45)


async def run_nano_ws_listener():
    def increment_msg_count():
        global msg_count
        msg_count += 1
        if msg_count % 1000 == 0:
            logger.info(msg_count)

    while True:
        try:
            # nano_ws = NanoWebSocket(url="wss://proxy.nanobrowse.com/ws")
            nano_ws = NanoWebSocket(url=WS_URL)
            await nano_ws.connect()
            await nano_ws.subscribe_new_unconfirmed_block()
            await nano_ws.subscribe_vote()
            await nano_ws.subscribe_started_election()
            await nano_ws.subscribe_confirmation(include_block=False)
            await nano_ws.subscribe_stopped_election()

            async for message in nano_ws.receive_messages():
                increment_msg_count()
                async with election_results_lock:
                    await process_message(message, elections_temp)
        except Exception as exc:
            logging.warn(
                f"Websocket closed with Exception : {exc}\n Reconnecting...")
            # attemp reconnect after 1 second (while true)
            await aio_sleep(1)
