import aiomcache
import orjson  # orjson is faster than the built-in json
from typing import Any


class CacheInterface:
    async def get(self, key):
        raise NotImplementedError

    async def set(self, key, value):
        raise NotImplementedError

    async def drop(self, key):
        raise NotImplementedError

    async def get_multi(self, keys):
        raise NotImplementedError

    async def set_multi(self, mapping):
        raise NotImplementedError

    async def drop_multi(self, keys):
        raise NotImplementedError


class InMemoryCache(CacheInterface):
    def __init__(self):
        self.store = {}

    async def get(self, key):
        return self.store.get(key, None)

    async def set(self, key, value):
        self.store[key] = value

    async def get_multi(self, keys):
        return {key: self.store[key] for key in keys if key in self.store}

    async def set_multi(self, mapping):
        for key, value in mapping.items():
            self.store[key] = value

    async def drop(self, key):
        self.store.pop(key, None)

    async def drop_multi(self, keys):
        for key in keys:
            await self.drop(key)


class MemcacheCache(CacheInterface):
    def __init__(self, host: str = 'localhost', port: int = 11211):
        self.client = aiomcache.Client(host, port)

    async def get(self, key: str) -> Any:
        value = await self.client.get(key.encode())
        if value is not None:
            return orjson.loads(value)
        return None

    async def set(self, key: str, value: Any, expire: int = 0):
        await self.client.set(key.encode(), orjson.dumps(value), exptime=expire)

    async def drop(self, key: str):
        await self.client.delete(key.encode())

    async def get_multi(self, keys: list[str]) -> dict:
        results = {}
        for key in keys:
            value = await self.get(key)
            if value is not None:
                results[key] = value
        return results

    async def set_multi(self, mapping: dict, expire: int = 0):
        for key, value in mapping.items():
            await self.set(key, value, expire)

    async def drop_multi(self, keys: list[str]):
        for key in keys:
            await self.drop(key)
