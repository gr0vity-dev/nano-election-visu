from rpc_client import get_online_reps
from known import known
from datetime import datetime


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
    for hash, info in block_data.get("blocks", {}).items():
        blocks.append({
            "hash": hash,
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
        rep["normal_delay"] = sum(
            rep["normal_delay"]) / len(rep["normal_delay"]) if rep["normal_delay"] else -1
        rep["final_delay"] = sum(
            rep["final_delay"]) / len(rep["final_delay"]) if rep["final_delay"] else -1
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


# def election_formatter(block_data, election_data, online_reps):

#     blocks = []
#     for hash, info in block_data.get("blocks", {}).items():
#         blocks.append({
#             "hash": hash,
#             "amount": info.get("amount", ""),
#             "account": info["contents"].get("account", ""),
#             "balance": info.get("balance", ""),
#             "height": info.get("height", "")
#         })

#     first_seen = int(election_data.get("first_seen", 0))
#     confirmed_timestamps = [int(ts)
#                             for ts in election_data.get("confirmed", [])]
#     confirmation_duration = min(
#         confirmed_timestamps) - first_seen if confirmed_timestamps else None

#     election_data.setdefault("votes", {})
#     election_data["votes"].setdefault("detail", [])

#     # Identifying the min timestamp for the first vote and first final vote
#     first_normal_vote_time = min(int(
#         vote["time"]) for vote in election_data["votes"]["detail"] if vote["type"] == "normal")
#     first_final_vote_time = min(int(
#         vote["time"]) for vote in election_data["votes"]["detail"] if vote["type"] == "final")

#     reps_summary = {}
#     for vote in election_data["votes"]["detail"]:
#         account = vote["account"]
#         account_formatted = vote["account_formatted"]
#         if account not in reps_summary:
#             reps_summary[account] = {
#                 "normal_votes": 0, "final_votes": 0, "normal_delay": [], "final_delay": [], "account_formatted": account_formatted}

#         vote_time = int(vote["time"])
#         if vote["type"] == "normal":
#             reps_summary[account]["normal_votes"] += 1
#             reps_summary[account]["normal_delay"].append(
#                 vote_time - first_normal_vote_time)
#         elif vote["type"] == "final":
#             reps_summary[account]["final_votes"] += 1
#             reps_summary[account]["final_delay"].append(
#                 vote_time - first_final_vote_time)

#     # Calculating average delays
#     for account, rep in reps_summary.items():
#         rep["normal_delay"] = sum(
#             rep["normal_delay"]) / len(rep["normal_delay"]) if rep["normal_delay"] else 0
#         rep["final_delay"] = sum(
#             rep["final_delay"]) / len(rep["final_delay"]) if rep["final_delay"] else 0
#         rep["weight"] = online_reps[account].get("votingweight")

#     for account, details in online_reps.items():
#         if account not in reps_summary:
#             reps_summary[account] = {
#                 "normal_votes": 0,
#                 "final_votes": 0,
#                 "normal_delay": -1,
#                 "final_delay": -1,
#                 "account_formatted": details["account_formatted"],
#                 "weight": details["votingweight"]
#             }

#     return {
#         "blocks": blocks[0],
#         "first_seen": first_seen,
#         "confirmation_duration": confirmation_duration,
#         "first_normal_vote_time": first_normal_vote_time,
#         "first_final_vote_time": first_final_vote_time,
#         "summary": reps_summary
#     }
