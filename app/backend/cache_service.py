from abc import ABC, abstractmethod
from typing import Any, Dict
import aiomcache
import orjson  # orjson is faster than the built-in json
import json  # fallback for 128bit integers
from typing import Any


class CacheInterface(ABC):
    @abstractmethod
    async def get(self, key: str) -> Any:
        pass

    @abstractmethod
    async def set(self, key: str, value: Any) -> None:
        pass

    @abstractmethod
    async def drop(self, key: str) -> None:
        pass

    @abstractmethod
    async def get_multi(self, keys: list) -> Dict[str, Any]:
        pass

    @abstractmethod
    async def set_multi(self, mapping: Dict[str, Any]) -> None:
        pass

    @abstractmethod
    async def drop_multi(self, keys: list) -> None:
        pass


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
    def __init__(self, host: str = 'localhost', port: int = 11211, prefix=""):
        self.client = aiomcache.Client(host, port)
        self.prefix = prefix

    def json_dumps(self, obj: Any) -> bytes:
        try:
            return orjson.dumps(obj)
        except TypeError as e:
            if str(e) == 'Integer exceeds 64-bit range':
                return json.dumps(obj).encode('utf-8')
            raise e

    def _prefixed_key(self, key: str) -> bytes:
        """Apply prefix to key and return as bytes."""
        return f"{self.prefix}{key}".encode()

    async def get(self, key: str) -> Any:
        value = await self.client.get(self._prefixed_key(key))
        if value is not None:
            return orjson.loads(value)
        return None

    async def set(self, key: str, value: Any, expire: int = 0):
        await self.client.set(self._prefixed_key(key), self.json_dumps(value), exptime=expire)

    async def drop(self, key: str):
        await self.client.delete(self._prefixed_key(key))

    async def get_multi(self, keys: list[str]) -> dict:
        results = {}
        for key in keys:
            value = await self.get(key)  # This already uses the prefixed key
            if value is not None:
                results[key] = value
        return results

    async def set_multi(self, mapping: dict, expire: int = 0):
        for key, value in mapping.items():
            # This already uses the prefixed key
            await self.set(key, value, expire)

    async def drop_multi(self, keys: list[str]):
        for key in keys:
            await self.drop(key)  # This already uses the prefixed key
