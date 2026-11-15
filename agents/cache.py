"""Small TTL cache for completed external reads; callers receive detached values."""
from collections import OrderedDict
from copy import deepcopy
from functools import wraps
from threading import Lock
from time import monotonic


def ttl_cache(seconds, maxsize):
    def decorate(fn):
        cache, lock = OrderedDict(), Lock()
        @wraps(fn)
        def wrapped(*args):
            now = monotonic()
            with lock:
                entry = cache.get(args)
                if entry and entry[0] > now:
                    cache.move_to_end(args)
                    return deepcopy(entry[1])
                cache.pop(args, None)
            value = fn(*args)  # Exceptions are never cached.
            with lock:
                cache[args] = (monotonic() + seconds, deepcopy(value))
                while len(cache) > maxsize:
                    cache.popitem(last=False)
            return value
        def clear():
            with lock:
                cache.clear()
        wrapped.cache_clear = clear
        return wrapped
    return decorate
