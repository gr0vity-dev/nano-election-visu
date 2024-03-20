from backend.rpc_client import get_online_reps, get_quorum
from known import known
from datetime import datetime
import json
import hashlib


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

    # Sort and limit the number of confirmed elections
    confirmed_sorted = dict(sorted(
        confirmed_elections.items(),
        key=lambda x: x[1].get('first_seen', 0),
        reverse=True
    )[:100])  # Slice to keep only the top elements

    # Sort and limit the number of unconfirmed elections
    unconfirmed_sorted = dict(sorted(
        unconfirmed_elections.items(),
        key=lambda x: (x[1].get('normal_weight', 0),
                       x[1].get('final_weight', 0)),
        reverse=True
    )[:5000])  # Slice to keep only the top elements

    # Combine sorted and limited dictionaries
    return current_hash, confirmed_sorted, unconfirmed_sorted
