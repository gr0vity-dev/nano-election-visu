class CacheInterface:
    async def get(self, key):
        raise NotImplementedError

    async def set(self, key, value):
        raise NotImplementedError

    async def get_multi(self, keys):
        raise NotImplementedError

    async def set_multi(self, mapping):
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
