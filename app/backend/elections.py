from backend.cache_service import CacheInterface


class ElectionHandler:
    def __init__(self, cache: CacheInterface):
        self.cache = cache

    async def merge_elections(self, delta):
        # Fetch relevant keys from the cache
        relevant_keys = delta.keys()
        current_electins = await self.cache.get_multi(relevant_keys)
        self._process_merge(current_electins, delta)
        await self.cache.set_multi(current_electins)

        return current_electins

    def _process_merge(self, current_electins, delta):
        for block_hash, delta_details in delta.items():
            if block_hash not in current_electins:
                current_electins[block_hash] = delta_details
            else:
                merge_details = current_electins[block_hash]
                merge_details["first_confirmed"] = merge_details["first_confirmed"] or delta_details["first_confirmed"]

                # Ensure lists and dictionaries are initialized if not present
                if "started" not in merge_details:
                    merge_details["started"] = []
                if "confirmed" not in merge_details:
                    merge_details["confirmed"] = []
                if "votes" not in merge_details:
                    merge_details["votes"] = {
                        "normal": 0, "final": 0, "detail": []}

                merge_details["started"].extend(
                    delta_details.get("started", []))
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
