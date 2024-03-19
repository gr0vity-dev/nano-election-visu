from data_processor import process_message
from nanows.api import NanoWebSocket
from asyncio import Lock, sleep as aio_sleep
import logging
from os import getenv

WS_URL = getenv("WS_URL")

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Quart")

#
election_results = {}
election_results_lock = Lock()


async def run_nano_ws_listener():
    i = 0
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
                async with election_results_lock:
                    i = i + 1
                    if i % 100 == 0:
                        logger.info(i)

                    process_message(message, election_results)
        except:
            # attemp reconnect after 1 second (while true)
            aio_sleep(1)
