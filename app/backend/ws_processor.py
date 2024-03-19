

async def process_message(message, election_results):
    topic = message.get("topic")
    msg = message.get("message")
    msg_time = int(message.get("time"))

    if topic == "vote":
        _process_vote_message(msg, election_results, msg_time)
    elif topic in ["started_election", "stopped_election", "confirmation"]:
        _process_event_message(msg, election_results, msg_time, topic)


def _process_vote_message(msg, election_results, msg_time):
    account = msg.get("account")
    timestamp = msg.get("timestamp")
    vote_type = "final" if timestamp == "18446744073709551615" else "normal"

    for block_hash in msg.get("blocks", []):
        _initialise_block_hash(election_results, block_hash, msg_time)

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


def _process_event_message(msg, election_results, msg_time, topic):
    block_hash = msg.get("hash")
    _initialise_block_hash(election_results, block_hash, msg_time)

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


def _initialise_block_hash(election_results, block_hash, msg_time):
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
