from rpc_client import get_online_reps
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
            "is_confirmed": False,
        }


def process_message(message, election_results):
    topic = message.get("topic")
    msg = message.get("message")
    msg_time = message.get("time")

    if topic == "vote":
        process_vote_message(msg, election_results, msg_time)
    elif topic in ["started_election", "stopped_election", "confirmation"]:
        process_event_message(msg, election_results, msg_time, topic)


def process_vote_message(msg, election_results, msg_time):
    online_reps = get_online_reps()
    account = msg.get("account")
    alias = known.get(account) or account
    weight = online_reps.get(account, {}).get("votingweight")
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
            "account": account,
            "account_formatted": alias,
            "weight": weight
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

    first_seen = int(election_data.get("first_seen", 0))
    confirmed_timestamps = [int(ts)
                            for ts in election_data.get("confirmed", [])]
    confirmation_seen = min(
        confirmed_timestamps) if confirmed_timestamps else None
    confirmation_duration = confirmation_seen - \
        first_seen if confirmed_timestamps else None

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
        rep["normal_delay"] = round(sum(
            rep["normal_delay"]) / len(rep["normal_delay"]), 2) if rep["normal_delay"] else -1
        rep["final_delay"] = round(sum(
            rep["final_delay"]) / len(rep["final_delay"]), 2) if rep["final_delay"] else -1
        rep["weight"] = online_reps.get(account, {}).get("votingweight", 0)
        rep["weight_percent"] = online_reps.get(
            account, {}).get("weight_percent", 0)

    for account, details in online_reps.items():
        if account not in reps_summary:
            reps_summary[account] = {
                "normal_votes": 0,
                "final_votes": 0,
                "normal_delay": -1,
                "final_delay": -1,
                "account_formatted": known.get(account) or account,
                "weight": details.get("votingweight", 0),
                "weight_percent": details.get("weight_percent", 0)
            }

    now = int(datetime.now().timestamp() * 1000)
    last_activity_seconds = (
        now - (last_final_vote_time or last_normal_vote_time)) // 1000 if (last_final_vote_time or last_normal_vote_time) else "No recent activity"
    return {
        "blocks": blocks if blocks else {},
        "first_seen": first_seen,
        "confirmation_seen": confirmation_seen,
        "confirmation_duration": confirmation_duration,
        "first_normal_vote_time": first_normal_vote_time,
        "first_final_vote_time": first_final_vote_time,
        "last_normal_vote_time": last_normal_vote_time,
        "last_final_vote_time": last_final_vote_time,
        "last_activity": last_activity_seconds,
        "summary": reps_summary
    }


def process_data_for_send(data, quorum, include_top_voters=10):
    data_to_send = {}
    quorum_delta = int(quorum.get("quorum_delta", "1"))

    confirmed_elections = {}
    unconfirmed_elections = {}
    now = int(datetime.now().timestamp() * 1000)

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
            vote.get("account_formatted", vote["account"])
            for vote in final_voters_sorted[:include_top_voters]
        ]
        data_to_send[block_hash]["first_final_voters"] = first_final_voter_aliases
        data_to_send[block_hash]["normal_weight_percent"] = (
            data_to_send[block_hash]["normal_weight"] / quorum_delta) * 100
        data_to_send[block_hash]["final_weight_percent"] = (
            data_to_send[block_hash]["final_weight"] / quorum_delta) * 100

        # Distribute elections into confirmed and unconfirmed
        if election.get("is_confirmed"):
            confirmed_elections[block_hash] = data_to_send[block_hash]
        else:
            unconfirmed_elections[block_hash] = data_to_send[block_hash]

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
    for block_hash, election in data.items():
        first_seen = int(election.get("first_seen", now))
        is_confirmed = election.get("is_confirmed", False)
        confirmation_seen = int(election.get("confirmed", [])[
            0] or 0) if is_confirmed else None
        data_to_send[block_hash]["active_since"] = (
            now - first_seen) // 1000 if first_seen else "N/A",
        data_to_send[block_hash]["confirmation_duration"] = confirmation_seen - \
            first_seen if is_confirmed else "N/A"

    return current_hash, data_to_send
