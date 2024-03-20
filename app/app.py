from quart import Quart, websocket, render_template, jsonify
from backend.ws_client import run_nano_ws_listener, get_election_results, trim_election_results, get_processed_elections
from backend.rpc_client import update_online_reps, get_block_info
from backend.data_processor import election_formatter
from os import getenv
import asyncio
import json
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Quart")

app = Quart(__name__)

clients = []
quorum = {}
online_reps = {}
previous_data_hash = None


@app.before_serving
async def startup():
    app.add_background_task(trim_election_results)
    app.add_background_task(refresh_quorum)
    app.add_background_task(broadcast)
    asyncio.create_task(run_nano_ws_listener())


async def get_election_data(hash):
    election_data = await get_election_results(hash)

    if not election_data:
        return {"error": "No election data found"}

    # Return all election data if no specific hash is provided
    return election_data


async def get_data_for_broadcast():
    processed_elections = get_processed_elections()
    return processed_elections


async def send_data_to_clients(clients_to_send, data):
    """Send data to specified clients."""
    for client in list(clients_to_send):  # Iterate over a copy of the specified clients list
        try:
            await client.send(json.dumps({"elections": data}))
        except Exception as e:
            logging.error("Error sending message: %s", e)
            clients.remove(client)


async def broadcast():
    global previous_data_hash
    while True:
        data_hash, data = await get_data_for_broadcast()
        if clients and data_hash != previous_data_hash:
            previous_data_hash = data_hash
            await send_data_to_clients(clients, data)

        await asyncio.sleep(0.5)


async def refresh_quorum():
    global quorum, online_reps
    while True:
        online_reps, quorum = await update_online_reps()
        await asyncio.sleep(60)


@app.websocket('/ws')
async def ws():
    current_client = websocket._get_current_object()
    clients.append(current_client)
    logger.info("New client connected: %s", current_client)
    try:
        _, data = await get_data_for_broadcast()  # Get the current data
        # Send only to the current client
        await send_data_to_clients([current_client], data)
    except Exception as e:
        logger.error("Error sending initial data to client: %s", e)

    try:
        while True:
            data = await websocket.receive()
            logger.info("Received message from client: %s", data)
    except Exception as e:
        logger.error("WebSocket error: %s", e)
    finally:
        # Clean up when a client disconnects
        clients.remove(current_client)
        logger.info("Client disconnected: %s", current_client)


@app.route('/')
async def index():
    return await render_template('index.html')


@app.route('/raw/<hash>')
async def raw(hash):
    election_data = await get_election_data(hash)
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
