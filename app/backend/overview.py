
from backend.cache_service import CacheInterface
from typing import Any, Dict, Tuple
import hashlib
import json
from datetime import datetime


class OverviewHandler:
    def __init__(self, cache: CacheInterface):
        self.cache = cache

    async def process_and_cache_elections(self, updated_overview: Dict[str, Any]) -> Tuple[str, Dict[str, Any], Dict[str, Any]]:
        """
        Processes updated election data, caches it, and retrieves a summary for view aggregation.
        """
        merged_overview = await self.retrieve_election_data()  # Assumes retrieval is adjusted to return the merged overview directly
        current_hash = await self.update_overview_data(
            merged_overview, updated_overview)
        return current_hash

    async def update_overview_data(self,
                                   merged_overview: Dict[str, Any],
                                   updated_overview: Dict[str, Any]) -> Tuple[str, Dict[str, Any], Dict[str, Any]]:
        confirmed_elections = {}
        unconfirmed_elections = {}

        # Update the merged overview directly if it's empty, else merge the updates.
        if not merged_overview:
            merged_overview = updated_overview
        else:
            for block_hash, delta_details in updated_overview.items():
                merged_overview[block_hash] = delta_details

        # Simplified loop: only categorize elections without adding time metrics.
        for block_hash, details in merged_overview.items():
            if details.get("is_confirmed", False):
                confirmed_elections[block_hash] = details
            else:
                unconfirmed_elections[block_hash] = details

        # Hash the overview without the removed time metrics for a stable comparison.
        elections_str = json.dumps(merged_overview, sort_keys=True).encode()
        current_hash = hashlib.sha256(elections_str).hexdigest()

        # Sort confirmed and unconfirmed elections.
        confirmed_sorted = self._sort_elections_by_key(
            confirmed_elections, 'first_seen')
        unconfirmed_sorted = self._sort_elections_by_multiple_keys(
            unconfirmed_elections, 'normal_weight', 'final_weight')

        # Extract updates for caching.
        updated_confirmed = {
            k: confirmed_sorted[k] for k in updated_overview if k in confirmed_sorted}
        updated_unconfirmed = {
            k: unconfirmed_sorted[k] for k in updated_overview if k in unconfirmed_sorted}

        # Cache or process sorted election data as needed.
        await self.cache_overview(updated_confirmed, updated_unconfirmed)
        await self.cache_overview_keys(confirmed_sorted, unconfirmed_sorted)

        return current_hash

    def _sort_elections_by_key(self, elections: Dict[str, Any], key: str) -> Dict[str, Any]:
        return dict(sorted(elections.items(), key=lambda x: x[1].get(key, 0), reverse=True))

    def _sort_elections_by_multiple_keys(self, elections: Dict[str, Any], *keys: str) -> Dict[str, Any]:
        return dict(sorted(elections.items(),
                           key=lambda x: tuple(x[1].get(k, 0) for k in keys),
                           reverse=True))

    async def cache_overview(self,
                             confirmed_elections: Dict[str, Any],
                             unconfirmed_elections: Dict[str, Any]) -> None:
        # Set multi operations for confirmed and unconfirmed elections with respective expiration times
        await self.cache.set_multi(confirmed_elections, expire=300)
        await self.cache.set_multi(unconfirmed_elections, expire=300)

    async def cache_overview_keys(self,
                                  confirmed_elections: Dict[str, Any],
                                  unconfirmed_elections: Dict[str, Any]) -> None:

        # Storing the keys of confirmed and unconfirmed elections for easy access
        await self.cache.set("confirmed_keys", list(confirmed_elections.keys()))
        await self.cache.set("unconfirmed_keys", list(unconfirmed_elections.keys()))

    async def retrieve_election_data(self,
                                     num_confirmed: int = None,
                                     num_unconfirmed: int = None) -> Dict[str, Any]:
        # Retrieve keys for confirmed and unconfirmed elections
        confirmed_keys = await self.cache.get("confirmed_keys") or []
        unconfirmed_keys = await self.cache.get("unconfirmed_keys") or []

        if num_confirmed:
            confirmed_keys = confirmed_keys[:num_confirmed]
        if num_unconfirmed:
            unconfirmed_keys = unconfirmed_keys[:num_unconfirmed]

        # Fetch election data based on the processed keys
        confirmed_elections = await self.cache.get_multi(confirmed_keys)
        unconfirmed_elections = await self.cache.get_multi(unconfirmed_keys)

        # Combine and return the fetched election data
        return {**confirmed_elections, **unconfirmed_elections}
