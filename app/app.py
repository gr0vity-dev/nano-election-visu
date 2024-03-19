import time
import asyncio
import json
from datetime import datetime
import logging
from quart import Quart, websocket, render_template, jsonify
from ws_client import run_nano_ws_listener, election_results, election_results_lock
from rpc_client import update_online_reps, get_block_info
from data_processor import election_formatter, process_data_for_send
import hashlib
from os import getenv


# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Quart")

app = Quart(__name__)

clients_data = {}
quorum = {}
online_reps = {}


@app.before_serving
async def startup():
    app.add_background_task(refresh_quorum)
    app.add_background_task(broadcast)
    asyncio.create_task(run_nano_ws_listener())

MAX_UNCONFIRMED = 2500
MAX_CONFIRMED = 20


async def get_election_data(hash=None):
    async with election_results_lock:
        if hash:
            # Return data for the specific hash if it exists
            election_data = election_results.get(
                hash, {"error": "No election data found"})
            return election_data

        # Return all election data if no specific hash is provided
        return election_results


async def get_data_for_broadcast():
    global election_results
    """Safely trims and copies data for broadcasting based on confirmation status."""
    async with election_results_lock:
        # Separate confirmed and unconfirmed elections, assuming each entry has an 'is_confirmed' flag
        unconfirmed = {k: v for k, v in election_results.items()
                       if not v.get('is_confirmed') and not v.get('is_stopped')}
        confirmed = {k: v for k, v in election_results.items()
                     if v.get('is_confirmed')}

        # Note: This step assumes dictionaries are in insertion (chronological) order.
        trimmed_unconfirmed = dict(
            list(unconfirmed.items())[-MAX_UNCONFIRMED:])
        trimmed_confirmed = dict(list(confirmed.items())[-MAX_CONFIRMED:])

        # Combine back the trimmed results for processing
        # election_results = {**trimmed_unconfirmed, **trimmed_confirmed}
        combined_data = {**trimmed_unconfirmed, **trimmed_confirmed}

    # Now, process and return the trimmed data for sending
    return process_data_for_send(combined_data, quorum, include_top_voters=0)


async def broadcast():
    while True:
        start_time = time.time()
        data_hash, data = await get_data_for_broadcast()
        duration = time.time() - start_time
        # logging.info(
        #     f"Preparing took {duration * 1000:.3f} ms for {len(election_results)} elections")
        if clients_data:  # Check if there are any connected clients
            for ws, ws_data in list(clients_data.items()):  # Iterate over clients
                try:
                    if data_hash != ws_data["hash"]:
                        await ws.send(json.dumps({"duration": duration, "count": len(data), "quorum": quorum, "elections": data}))
                        # Update the hash for the client
                        ws_data["hash"] = data_hash
                except Exception as e:
                    print(f"Error sending message: {e}")
                    clients_data.pop(ws, None)  # Remove the client on error
        await asyncio.sleep(0.5)


async def refresh_quorum():
    global quorum, online_reps
    while True:
        online_reps, quorum = await update_online_reps()
        await asyncio.sleep(60)


@app.websocket('/ws')
async def ws():
    current_client = websocket._get_current_object()
    # Initialize the client's data with a None hash (or use an appropriate default value)
    clients_data[current_client] = {"hash": None}
    logger.info(f"New client connected: {current_client}")
    try:
        while True:
            data = await websocket.receive()
            logger.info(f"Received message from client: {data}")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        # Clean up when a client disconnects
        clients_data.pop(current_client, None)
        logger.info(f"Client disconnected: {current_client}")


@app.route('/')
async def index():
    return await render_template('index.html')


@app.route('/raw')
async def raw():
    election_data = await get_election_data()
    return election_data


@app.route('/election_details/', defaults={'hash': None})
@app.route('/election_details/<hash>')
async def get_election(hash):
    election_data = await get_election_data(hash)
    block_info = await get_block_info(hash)

    response = election_formatter(block_info, election_data, online_reps)

    # If hash is provided and no data is found, return a not found response
    if hash and not election_data:
        return jsonify({"error": "Election data not found"}), 404
    return await render_template('election_detail.html', election_data=response, block_explorer=getenv("BLOCK_EXPLORER"))


@app.route('/api/election_details/', defaults={'hash': None})
@app.route('/api/election_details/<hash>')
async def api_get_election(hash):
    election_data = await get_election_data(hash)
    block_info = await get_block_info(hash)

    response = election_formatter(block_info, election_data, online_reps)
    return response


if __name__ == '__main__':
    app.run(port=5000)
