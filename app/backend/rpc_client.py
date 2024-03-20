import aiohttp
import json
from nanorpc.client import NanoRpcTyped
from asyncio import gather, Lock, sleep as aio_sleep
from os import getenv
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Quart")

RPC_URL = getenv("RPC_URL")
RPC_USERNAME = getenv("RPC_USERNAME")
RPC_PASSWORD = getenv("RPC_PASSWORD")
RPC_RECONNECT_DURATINO = 1  # duration until recconnect on failure

rpc = None
online_reps = {}
confirmation_quorum = {}


def get_nanorpc_client():

    # Initialize and return the NanoRpc client
    return NanoRpcTyped(url=RPC_URL,
                        username=RPC_USERNAME,
                        password=RPC_PASSWORD,
                        wrap_json=True)


async def get_rpc():
    global rpc
    while True:
        try:
            rpc = rpc or get_nanorpc_client()
            break
        except Exception as exc:
            rpc = None
            logging.warn(
                f"RPC closed with Exception : {exc}\n Reconnecting...")
            aio_sleep(RPC_RECONNECT_DURATINO)
    return rpc


async def fetch_http(url, session, method='get', payload=None):
    if method == 'post':
        async with session.post(url, data=json.dumps(payload)) as response:
            return await response.json()
    else:
        async with session.get(url) as response:
            return await response.json()


# async def fetch_online_reps(session):
#     url = "https://nanobrowse.com/api/reps_online/"
#     return await fetch_http(url, session, 'get')


async def get_online_reps():
    return online_reps


async def get_quorum():
    return confirmation_quorum


async def update_online_reps():
    global online_reps, confirmation_quorum

    online_reps, confirmation_quorum = await fetch_online_reps()
    return online_reps, confirmation_quorum


async def get_block_info(block_hash=None):
    if block_hash is None or "":
        return {}
    rpc = await get_rpc()
    hashes = [block_hash]

    response = await rpc.blocks_info(hashes, json_block="true", source="true", receive_hash="true")
    return response


async def fetch_online_reps():
    rpc = await get_rpc()
    tasks = {
        "online_reps": rpc.representatives_online(weight=True),
        "telemetry": rpc.telemetry(raw=True),
        "confirmation_quorum": rpc.confirmation_quorum(peer_details=True)
    }

    results = await execute_and_handle_errors(tasks)

    return await transform_reps_online_data(results)


def extend_telemetry_with_account(telemetry_peers, confirmation_quorum_peers):
    # Prepare IP and port from telemetry data for matching
    telemetry_dict = {
        f"[{peer['address']}]:{peer['port']}": peer for peer in telemetry_peers
    }

    # Prepare IP from confirmation quorum peers for matching
    formatted_peers = {
        f"{peer['ip']}": peer["account"]
        for peer in confirmation_quorum_peers
    }

    # Create a dictionary with the account as key, merging data from both sources
    merged_data = {}
    for ip, account in formatted_peers.items():
        telemetry_info = {}
        telemetry_info["account"] = account
        telemetry_info["ip"] = ip
        if ip in telemetry_dict:
            telemetry_info.update(telemetry_dict[ip])
            # Assign the telemetry info directly to the account in the merged_data dictionary
            merged_data[account] = telemetry_info

    return merged_data


async def transform_reps_online_data(data):
    representatives = data["online_reps"].get("representatives", {})
    confirmation_quorum = data["confirmation_quorum"]
    confirmation_quorum_peers = confirmation_quorum.pop("peers")
    telemetry_peers = data["telemetry"].get("metrics")

    extended_telemetry = extend_telemetry_with_account(
        telemetry_peers, confirmation_quorum_peers)

    # Ensure representatives is a dictionary
    if not isinstance(representatives, dict):
        return []  # or handle the error as appropriate for your application

    # Calculate the total weight
    total_weight = sum(int(rep.get("weight", 0))
                       for rep in representatives.values())

    # Sort representatives by weight in descending order
    sorted_reps = sorted(representatives.items(),
                         key=lambda x: int(x[1].get("weight", 0)), reverse=True)

    online_reps = {}
    for account, info in sorted_reps:
        account_weight = int(info.get("weight", 0))
        tac = extended_telemetry.get(account, {})
        node_maker_telemetry = tac.get("maker")
        node_id = tac.get("node_id")

        # Add the transformed data
        online_reps[account] = {
            "account": account,
            "votingweight": account_weight,
            "weight": account_weight,
            "weight_percent": (account_weight / total_weight) * 100,
            "node_maker": node_maker_telemetry,
            "node_version_telemetry": format_version(tac.get("major_version"), tac.get(
                "minor_version"), tac.get("patch_version"), tac.get("pre_release_version")),
            "node_id": node_id
        }

    return online_reps, confirmation_quorum


async def execute_and_handle_errors(tasks, droppable_errors=None):
    if droppable_errors is None:
        droppable_errors = []

    try:
        results = await gather(*tasks.values(), return_exceptions=True)
        results_dict = dict(zip(tasks.keys(), results))

        # Check each result for errors. Assuming that errors in responses are indicated
        for _, result in results_dict.items():
            error_msg = "An unexpected error occurred. Please try again later."
            if isinstance(result, dict) and result.get("error") in droppable_errors:
                # Move the error to ignored_error if in the list of droppable errors.
                # Avoids raising a ValueError
                result["ignored_error"] = result.pop("error")

            if isinstance(result, dict) and "error" in result or isinstance(result, Exception):
                # Adjust to handle both dict and Exception cases
                error_msg = result.get("msg", result.get("error", error_msg)) if isinstance(
                    result, dict) else str(result)
                raise ValueError(error_msg)
        return results_dict
    except ValueError as exc:
        raise exc
    except Exception as exc:
        raise ValueError(
            f"An unexpected error occurred: {exc}\nPlease try again later.")


def format_version(major, minor, patch, pre_release):
    # List of version parts
    version_numbers = [major, minor, pre_release]
    # Filter out any None values
    valid_versions = [str(v) for v in version_numbers if v is not None]

    # Join the remaining parts with dots, or return a default value if empty
    return '.'.join(valid_versions) if valid_versions else "0.0.0"
