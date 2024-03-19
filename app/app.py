import time
import asyncio
import json
from datetime import datetime
import logging
from quart import Quart, websocket, render_template, jsonify
from ws_client import run_nano_ws_listener, election_results, election_results_lock
from rpc_client import update_online_reps, get_block_info
from data_processor import election_formatter
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
    return process_data_for_send(combined_data)


def process_data_for_send(data, include_top_voters=10):
    data_to_send = {}
    quorum_delta = int(quorum.get("quorum_delta", "1"))

    confirmed_elections = {}
    unconfirmed_elections = {}
    now = int(datetime.now().timestamp() * 1000)

    for hash, election in data.items():
        # Initialize data structure

        data_to_send[hash] = {
            "normal_weight": 0,
            "final_weight": 0,
            "is_active": election.get("is_active", False),
            "is_stopped": election.get("is_stopped", False),
            "is_confirmed": election.get("is_confirmed", False),
            "normal_votes": election.get("votes", {}).get("normal", 0),
            "final_votes": election.get("votes", {}).get("final", 0),
            "first_seen":  election.get("first_seen", 0),
            "first_final_voters": []
        }

        seen_accounts_normal = set()
        seen_accounts_final = set()
        final_voters = []

        # Process votes in a single pass
        for vote in election["votes"]["detail"]:
            current_weight = vote["weight"] or 0
            account = vote["account"]
            vote_type = vote["type"]

            # Handle normal votes
            if vote_type == "normal" and account not in seen_accounts_normal:
                data_to_send[hash]["normal_weight"] += current_weight
                seen_accounts_normal.add(account)
            # Handle final votes
            elif vote_type == "final":
                if account not in seen_accounts_final:
                    data_to_send[hash]["final_weight"] += current_weight
                    seen_accounts_final.add(account)
                final_voters.append(vote)

        # Sort and select top final voters after processing all votes
        final_voters_sorted = sorted(final_voters, key=lambda x: x["time"])
        first_final_voter_aliases = [
            vote.get("account_formatted", vote["account"])
            for vote in final_voters_sorted[:include_top_voters]
        ]
        data_to_send[hash]["first_final_voters"] = first_final_voter_aliases
        data_to_send[hash]["normal_weight_percent"] = (
            data_to_send[hash]["normal_weight"] / quorum_delta) * 100
        data_to_send[hash]["final_weight_percent"] = (
            data_to_send[hash]["final_weight"] / quorum_delta) * 100

        # Distribute elections into confirmed and unconfirmed
        if election.get("is_confirmed"):
            confirmed_elections[hash] = data_to_send[hash]
        else:
            unconfirmed_elections[hash] = data_to_send[hash]

    # Sort confirmed elections by 'first_seen' in reverse order

    confirmed_sorted = dict(sorted(
        confirmed_elections.items(),
        key=lambda x: x[1].get('first_seen', 0),
        reverse=True
    ))

    unconfirmed_sorted = dict(sorted(
        unconfirmed_elections.items(),
        key=lambda x: (x[1].get('normal_weight', 0),
                       x[1].get('final_weight', 0)),
        reverse=True
    ))

    # # Combine sorted dictionaries
    data_to_send = {**unconfirmed_sorted, **confirmed_sorted}

    elections_str = json.dumps(data_to_send, sort_keys=True).encode()
    current_hash = hashlib.sha256(elections_str).hexdigest()

    # Exclude time changes from being hased, else it will always update!
    for hash, election in data.items():
        first_seen = int(election.get("first_seen", now))
        is_confirmed = election.get("is_confirmed", False)
        confirmation_seen = int(election.get("confirmed", [])[
            0] or 0) if is_confirmed else None
        data_to_send[hash]["active_since"] = (
            now - first_seen) // 1000 if first_seen else "N/A",
        data_to_send[hash]["confirmation_duration"] = confirmation_seen - \
            first_seen if is_confirmed else "N/A"

    return current_hash, data_to_send


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
