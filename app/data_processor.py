from rpc_client import get_online_reps, get_quorum
from known import known
from datetime import datetime
import json
import hashlib


def initialise_block_hash(election_results, block_hash, msg_time):
    if block_hash not in election_results:
        election_results[block_hash] = {
            "votes": {
                "normal": 0,
                "final": 0,
                "detail": []
            },
            "first_seen": msg_time,
            "started": [],
            "is_started": False,
            "stopped": [],
            "is_stopped": False,
            "confirmed": [],
            "first_confirmed": None,
            "is_confirmed": False,
        }


async def process_message(message, election_results):
    topic = message.get("topic")
    msg = message.get("message")
    msg_time = int(message.get("time"))

    if topic == "vote":
        await process_vote_message(msg, election_results, msg_time)
    elif topic in ["started_election", "stopped_election", "confirmation"]:
        process_event_message(msg, election_results, msg_time, topic)


async def process_vote_message(msg, election_results, msg_time):
    account = msg.get("account")
    timestamp = msg.get("timestamp")
    vote_type = "final" if timestamp == "18446744073709551615" else "normal"

    for block_hash in msg.get("blocks", []):
        initialise_block_hash(election_results, block_hash, msg_time)

        # Increment vote count
        election_results[block_hash]['votes'][vote_type] += 1

        # Add vote detail
        election_results[block_hash]['votes']['detail'].append({
            "type": vote_type,
            "time": msg_time,
            "account": account
        })

        # Sort vote details by time
        election_results[block_hash]['votes']['detail'].sort(
            key=lambda x: x['time'])


def process_event_message(msg, election_results, msg_time, topic):
    block_hash = msg.get("hash")
    initialise_block_hash(election_results, block_hash, msg_time)

    if topic == "started_election":
        election_results[block_hash]['started'].append(msg_time)
        election_results[block_hash]['is_active'] = True
        election_results[block_hash]['is_started'] = True
    elif topic == "stopped_election":
        election_results[block_hash]['stopped'].append(msg_time)
        election_results[block_hash]['is_active'] = False
        election_results[block_hash]['is_stopped'] = True
    elif topic == "confirmation":
        election_results[block_hash]['confirmed'].append(msg_time)
        election_results[block_hash]['is_active'] = False
        election_results[block_hash]['is_confirmed'] = True
        election_results[block_hash]['amount'] = msg.get("amount")
        election_results[block_hash]["first_confirmed"] = msg_time


def election_formatter(block_data, election_data, online_reps):

    blocks = []
    for block_hash, info in block_data.get("blocks", {}).items():
        blocks.append({
            "hash": block_hash,
            "confirmed": info.get("confirmed") == "true",
            "amount": info.get("amount", ""),
            "account": info.get("contents", {}).get("account", ""),
            "balance": info.get("balance", ""),
            "height": info.get("height", ""),
            "block_type": info.get("subtype", ""),
            "receive_hash": info.get("receive_hash", ""),
            "source_account": info.get("source_account", ""),
        })

    first_seen = election_data.get("first_seen")
    first_confirmed = election_data.get("first_confirmed")
    confirmation_duration = first_confirmed - \
        first_seen if election_data.get("is_confirmed") else None

    votes_detail = election_data.get("votes", {}).get("detail", [])

    # Guard against empty detail with if-else statements for time calculations
    first_normal_vote_time = None
    first_final_vote_time = None
    last_normal_vote_time = None
    last_final_vote_time = None
    if votes_detail:
        normal_times = [int(vote["time"])
                        for vote in votes_detail if vote.get("type") == "normal"]
        final_times = [int(vote["time"])
                       for vote in votes_detail if vote.get("type") == "final"]
        first_normal_vote_time = min(normal_times) if normal_times else None
        first_final_vote_time = min(final_times) if final_times else None
        last_normal_vote_time = max(normal_times) if normal_times else None
        last_final_vote_time = max(final_times) if final_times else None

    reps_summary = {}
    for vote in votes_detail:
        account = vote.get("account", "")
        account_formatted = known.get(account) or account
        if account not in reps_summary:
            reps_summary[account] = {
                "normal_votes": 0, "final_votes": 0, "normal_delay": [], "final_delay": [], "account_formatted": account_formatted}

        vote_time = int(vote.get("time", "0"))
        if vote.get("type") == "normal" and first_normal_vote_time is not None:
            reps_summary[account]["normal_votes"] += 1
            reps_summary[account]["normal_delay"].append(
                vote_time - first_normal_vote_time)
        elif vote.get("type") == "final" and first_final_vote_time is not None:
            reps_summary[account]["final_votes"] += 1
            reps_summary[account]["final_delay"].append(
                vote_time - first_final_vote_time)

    # Calculating average delays
    for account, rep in reps_summary.items():
        rep["normal_delay"] = min(
            rep["normal_delay"]) if rep["normal_delay"] else -1
        rep["final_delay"] = min(
            rep["final_delay"]) if rep["final_delay"] else -1
        rep["weight"] = online_reps.get(account, {}).get("votingweight", 0)
        rep["weight_percent"] = online_reps.get(
            account, {}).get("weight_percent", 0)
        rep["node_version_telemetry"] = online_reps.get(
            account, {}).get("node_version_telemetry", "N/A")

    for account, details in online_reps.items():
        if account not in reps_summary:
            reps_summary[account] = {
                "normal_votes": 0,
                "final_votes": 0,
                "normal_delay": -1,
                "final_delay": -1,
                "account_formatted": known.get(account) or account,
                "weight": details.get("votingweight", 0),
                "weight_percent": details.get("weight_percent", 0),
                "node_version_telemetry": details.get("node_version_telemetry", "N/A")
            }

    now = int(datetime.now().timestamp() * 1000)
    last_activity_seconds = (
        now - (last_final_vote_time or last_normal_vote_time)) // 1000 if (last_final_vote_time or last_normal_vote_time) else "No recent activity"
    return {
        "blocks": blocks if blocks else {},
        "first_seen": first_seen,
        "confirmation_seen": first_confirmed,
        "confirmation_duration": confirmation_duration,
        "first_normal_vote_time": first_normal_vote_time,
        "first_final_vote_time": first_final_vote_time,
        "last_normal_vote_time": last_normal_vote_time,
        "last_final_vote_time": last_final_vote_time,
        "last_activity": last_activity_seconds,
        "summary": reps_summary
    }


async def process_data_for_send(data, include_top_voters=5):
    data_to_send = {}
    online_reps = await get_online_reps()
    quorum = await get_quorum()
    quorum_delta = int(quorum.get("quorum_delta", "1"))

    for block_hash, election in data.items():
        # Initialize data structure

        data_to_send[block_hash] = {
            "normal_weight": 0,
            "final_weight": 0,
            "is_active": election.get("is_active", False),
            "is_stopped": election.get("is_stopped", False),
            "is_confirmed": election.get("is_confirmed", False),
            "normal_votes": election.get("votes", {}).get("normal", 0),
            "final_votes": election.get("votes", {}).get("final", 0),
            "first_seen":  election["first_seen"],
            "first_confirmed":  election["first_confirmed"],
            "first_final_voters": []
        }

        seen_accounts_normal = set()
        seen_accounts_final = set()
        final_voters = []

        # Process votes in a single pass

        for vote in election["votes"]["detail"]:
            account = vote["account"]
            current_weight = online_reps.get(
                account, {}).get("votingweight") or 0
            vote_type = vote["type"]

            # Handle normal votes
            if vote_type == "normal" and account not in seen_accounts_normal:
                data_to_send[block_hash]["normal_weight"] += current_weight
                seen_accounts_normal.add(account)
            # Handle final votes
            elif vote_type == "final":
                if account not in seen_accounts_final:
                    data_to_send[block_hash]["final_weight"] += current_weight
                    seen_accounts_final.add(account)
                final_voters.append(vote)

        # Sort and select top final voters after processing all votes
        final_voters_sorted = sorted(final_voters, key=lambda x: x["time"])
        first_final_voter_aliases = [
            known.get(vote["account"], vote["account"])
            for vote in final_voters_sorted[:include_top_voters]
        ]
        data_to_send[block_hash]["first_final_voters"] = first_final_voter_aliases
        data_to_send[block_hash]["normal_weight_percent"] = (
            data_to_send[block_hash]["normal_weight"] / quorum_delta) * 100
        data_to_send[block_hash]["final_weight_percent"] = (
            data_to_send[block_hash]["final_weight"] / quorum_delta) * 100

    return data_to_send


def merge_overview_data(merged_overview, delta, include_top_voters=5):
    # Fallback to delta if merged_overview is not initialized
    now = int(datetime.now().timestamp() * 1000)
    confirmed_elections = {}
    unconfirmed_elections = {}

    if not merged_overview:
        merged_overview = delta
    else:
        for block_hash, delta_details in delta.items():
            if block_hash not in merged_overview:
                merged_overview[block_hash] = delta_details
                continue

            # Get current values safely, defaulting to 0 or appropriate types if not found
            merged_details = merged_overview[block_hash]
            merged_details["first_confirmed"] = delta_details["first_confirmed"] or merged_details["first_confirmed"]
            merged_details["normal_weight"] = merged_details.get(
                "normal_weight", 0) + delta_details.get("normal_weight", 0)
            merged_details["final_weight"] = merged_details.get(
                "final_weight", 0) + delta_details.get("final_weight", 0)
            merged_details["normal_votes"] = merged_details.get(
                "normal_votes", 0) + delta_details.get("normal_votes", 0)
            merged_details["final_votes"] = merged_details.get(
                "final_votes", 0) + delta_details.get("final_votes", 0)
            merged_details["normal_weight_percent"] = merged_details.get(
                "normal_weight_percent", 0) + delta_details.get("normal_weight_percent", 0)
            merged_details["final_weight_percent"] = merged_details.get(
                "final_weight_percent", 0) + delta_details.get("final_weight_percent", 0)

            # Handle lists and other types explicitly
            if len(merged_details["first_final_voters"]) < include_top_voters:
                merged_details["first_final_voters"] = merged_details.get(
                    "first_final_voters", []) + delta_details.get("first_final_voters", [])
            merged_details["active_since"] = delta_details.get(
                "active_since", merged_details.get("active_since"))
            merged_details["confirmation_duration"] = merged_details.get(
                "confirmation_duration") or delta_details.get("confirmation_duration")

            # Update flags based on details, safely handling missing values
            is_stopped = delta_details.get("is_stopped", False)
            is_confirmed = delta_details.get("is_confirmed", False)
            is_active = delta_details.get(
                "is_active", merged_details.get("is_active", False))

            if is_stopped:
                merged_details["is_active"] = False
                merged_details["is_stopped"] = True
            elif is_confirmed:
                merged_details["is_active"] = False
                merged_details["is_stopped"] = False
                merged_details["is_confirmed"] = True
            elif is_active:
                merged_details["is_stopped"] = False
                merged_details["is_active"] = True

    elections_str = json.dumps(merged_overview, sort_keys=True).encode()
    current_hash = hashlib.sha256(elections_str).hexdigest()

    # Exclude time changes from being hased, else it will always update!

    for block_hash, details in merged_overview.items():
        first_seen = details["first_seen"]
        first_confirmed = details["first_confirmed"]
        is_confirmed = details.get("is_confirmed", False)
        merged_overview[block_hash]["active_since"] = (
            now - first_seen) // 1000
        merged_overview[block_hash]["confirmation_duration"] = first_confirmed - \
            first_seen if details["first_confirmed"] else None

        if details.get("is_confirmed"):
            confirmed_elections[block_hash] = merged_overview[block_hash]
        else:
            unconfirmed_elections[block_hash] = merged_overview[block_hash]

    # Sort and limit the number of confirmed elections to 100
    confirmed_sorted = dict(sorted(
        confirmed_elections.items(),
        key=lambda x: x[1].get('first_seen', 0),
        reverse=True
    )[:100])  # Slice to keep only the top 100

    # Sort and limit the number of unconfirmed elections to 1500
    unconfirmed_sorted = dict(sorted(
        unconfirmed_elections.items(),
        key=lambda x: (x[1].get('normal_weight', 0),
                       x[1].get('final_weight', 0)),
        reverse=True
    )[:5000])  # Slice to keep only the top 1500

    # Combine sorted and limited dictionaries

    return current_hash, confirmed_sorted, unconfirmed_sorted


def update_overview_data(merged_overview, updated_overview, include_top_voters=5):
    # Fallback to delta if merged_overview is not initialized
    now = int(datetime.now().timestamp() * 1000)
    confirmed_elections = {}
    unconfirmed_elections = {}

    if not merged_overview:
        merged_overview = updated_overview
    else:
        for block_hash, delta_details in updated_overview.items():
            merged_overview[block_hash] = delta_details

    elections_str = json.dumps(merged_overview, sort_keys=True).encode()
    current_hash = hashlib.sha256(elections_str).hexdigest()

    # Exclude time changes from being hased, else it will always update!

    for block_hash, details in merged_overview.items():
        first_seen = details["first_seen"]
        first_confirmed = details["first_confirmed"]
        is_confirmed = details.get("is_confirmed", False)
        merged_overview[block_hash]["active_since"] = (
            now - first_seen) // 1000
        merged_overview[block_hash]["confirmation_duration"] = first_confirmed - \
            first_seen if details["first_confirmed"] else None

        if is_confirmed:
            confirmed_elections[block_hash] = merged_overview[block_hash]
        else:
            unconfirmed_elections[block_hash] = merged_overview[block_hash]

    # Sort and limit the number of confirmed elections to 100
    confirmed_sorted = dict(sorted(
        confirmed_elections.items(),
        key=lambda x: x[1].get('first_seen', 0),
        reverse=True
    )[:100])  # Slice to keep only the top 100

    # Sort and limit the number of unconfirmed elections to 1500
    unconfirmed_sorted = dict(sorted(
        unconfirmed_elections.items(),
        key=lambda x: (x[1].get('normal_weight', 0),
                       x[1].get('final_weight', 0)),
        reverse=True
    )[:5000])  # Slice to keep only the top 1500

    # Combine sorted and limited dictionaries

    return current_hash, confirmed_sorted, unconfirmed_sorted


def merge_elections_raw(elections_all, delta):
    updated_elections = {}

    if not elections_all:
        elections_all = delta
        updated_elections = delta
        return elections_all, updated_elections

    for block_hash, delta_details in delta.items():
        if block_hash not in elections_all:
            elections_all[block_hash] = delta_details
            updated_elections[block_hash] = delta_details
        else:
            merge_details = elections_all[block_hash]
            merge_details["first_confirmed"] = delta_details["first_confirmed"] or merge_details["first_confirmed"]

            # Ensure lists and dictionaries are initialized if not present
            if "started" not in merge_details:
                merge_details["started"] = []
            if "confirmed" not in merge_details:
                merge_details["confirmed"] = []
            if "votes" not in merge_details:
                merge_details["votes"] = {
                    "normal": 0, "final": 0, "detail": []}

            merge_details["started"].extend(delta_details.get("started", []))
            merge_details["confirmed"].extend(
                delta_details.get("confirmed", []))

            for vote_type in ["normal", "final"]:
                merge_details["votes"][vote_type] += delta_details.get(
                    "votes", {}).get(vote_type, 0)

            merge_details["votes"]["detail"].extend(
                delta_details.get("votes", {}).get("detail", []))

            # Update the flags directly in merge_details
            is_stopped = delta_details.get("is_stopped", False)
            is_confirmed = delta_details.get("is_confirmed", False)
            is_active = delta_details.get(
                "is_active", merge_details.get("is_active", False))

            if is_stopped:
                merge_details["is_active"] = False
                merge_details["is_stopped"] = True
            elif is_confirmed:
                merge_details["is_active"] = False
                merge_details["is_stopped"] = False
                merge_details["is_confirmed"] = True
            elif is_active:
                merge_details["is_stopped"] = False
                merge_details["is_active"] = True

            updated_elections[block_hash] = merge_details

    return elections_all, updated_elections


def merge_processed_election_delta(processed_elections, delta):
    if not processed_elections:
        processed_elections = delta
        return

    for hash, details in delta.items():
        if hash not in processed_elections:
            processed_elections[hash] = details
        else:
            existing_election_data = processed_elections[hash]
            existing_election_data.setdefaul(
                "confirmation_duration", details.get("confirmation_duration"))
            existing_election_data.setdefaul(
                "confirmation_seen", details.get("confirmation_seen"))
            existing_election_data.setdefaul(
                "first_final_vote_time", details.get("first_final_vote_time"))
            existing_election_data.setdefaul(
                "first_normal_vote_time", details.get("first_normal_vote_time"))
            existing_election_data.setdefaul(
                "last_activity", details.get("last_activity"))
            existing_election_data.setdefaul(
                "last_final_vote_time", details.get("last_final_vote_time"))
            existing_election_data.setdefaul(
                "last_normal_vote_time", details.get("last_normal_vote_time"))

            existing_summary = existing_election_data.get("summary", {})
            new_summary = processed_elections[hash].get("summary", {})
            for account, account_details in new_summary:
                if account not in existing_summary:
                    existing_summary[account] = account_details
                else:
                    # summary entry already exists and needs to be updated
                    existing_account_summary = existing_summary[account]
                    if existing_account_summary["normal_delay"] == -1:
                        existing_account_summary["normal_delay"] = account_details["normal_delay"]
                    if existing_account_summary["final_delay"] == -1:
                        existing_account_summary["final_delay"] = account_details["final_delay"]
                    existing_account_summary["normal_votes"] += account_details["normal_votes"]
                    existing_account_summary["final_votes"] += account_details["final_votes"]
