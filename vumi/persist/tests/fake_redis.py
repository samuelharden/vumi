# -*- test-case-name: vumi.persist.tests.test_fake_redis -*-

import fnmatch
from functools import wraps

from twisted.internet import reactor
from twisted.internet.defer import Deferred


def maybe_async(func):
    @wraps(func)
    def wrapper(self, *args, **kw):
        result = func(self, *args, **kw)
        if self._is_async:
            d = Deferred()
            reactor.callLater(0, d.callback, result)
            return d
        return result
    wrapper.sync = func
    return wrapper


class FakeRedis(object):
    """In process and memory implementation of redis-like data store.

    It's intended to match the Python redis module API closely so that
    it can be used in place of the redis module when testing.

    Known limitations:

    * Exceptions raised are not guaranteed to match the exception
      types raised by the real Python redis module.
    """

    def __init__(self, async=False):
        self._data = {}
        self._expiries = {}
        self._is_async = async

    def teardown(self):
        self._clean_up_expires()

    def _clean_up_expires(self):
        for key in self._expiries.keys():
            delayed = self._expiries.pop(key)
            if not delayed.cancelled:
                delayed.cancel()

    # Global operations

    @maybe_async
    def exists(self, key):
        return key in self._data

    @maybe_async
    def keys(self, pattern='*'):
        return fnmatch.filter(self._data.keys(), pattern)

    @maybe_async
    def flushdb(self):
        self._data = {}

    # String operations

    @maybe_async
    def get(self, key):
        return self._data.get(key)

    @maybe_async
    def set(self, key, value):
        value = str(value)  # set() sets string value
        self._data[key] = value

    @maybe_async
    def delete(self, key):
        existed = (key in self._data)
        self._data.pop(key, None)
        return existed

    # Integer operations

    # The python redis lib combines incr & incrby into incr(key, increment=1)
    @maybe_async
    def incr(self, key, increment=1):
        old_value = self._data.get(key)
        if old_value is None:
            old_value = 0
        new_value = int(old_value) + increment
        self.set.sync(self, key, new_value)
        return new_value

    # Hash operations

    @maybe_async
    def hset(self, key, field, value):
        mapping = self._data.setdefault(key, {})
        new_field = field not in mapping
        mapping[field] = unicode(value)
        return int(new_field)

    @maybe_async
    def hget(self, key, field):
        return self._data.get(key, {}).get(field)

    @maybe_async
    def hdel(self, key, *fields):
        mapping = self._data.get(key)
        if mapping is None:
            return 0
        deleted = 0
        for field in fields:
            if field in mapping:
                del mapping[field]
                deleted += 1
        return deleted

    @maybe_async
    def hmset(self, key, mapping):
        hval = self._data.setdefault(key, {})
        hval.update(dict([(key, unicode(value))
            for key, value in mapping.items()]))

    @maybe_async
    def hgetall(self, key):
        return self._data.get(key, {}).copy()

    @maybe_async
    def hlen(self, key):
        return len(self._data.get(key, {}))

    @maybe_async
    def hvals(self, key):
        return self._data.get(key, {}).values()

    @maybe_async
    def hincrby(self, key, field, amount=1):
        value = self._data.get(key, {}).get(field, "0")
        # the int(str(..)) coerces amount to an int but rejects floats
        value = int(value) + int(str(amount))
        self._data.setdefault(key, {})[field] = str(value)
        return value

    @maybe_async
    def hexists(self, key, field):
        return int(field in self._data.get(key, {}))

    # Set operations

    @maybe_async
    def sadd(self, key, *values):
        sval = self._data.setdefault(key, set())
        sval.update(map(unicode, values))

    @maybe_async
    def smembers(self, key):
        return self._data.get(key, set())

    @maybe_async
    def spop(self, key):
        sval = self._data.get(key, set())
        if not sval:
            return None
        return sval.pop()

    @maybe_async
    def srem(self, key, value):
        sval = self._data.get(key, set())
        if value in sval:
            sval.remove(value)
            return 1
        return 0

    @maybe_async
    def scard(self, key):
        return len(self._data.get(key, set()))

    @maybe_async
    def smove(self, src, dst, value):
        result = self.srem.sync(self, src, value)
        if result:
            self.sadd.sync(self, dst, value)
        return result

    @maybe_async
    def sunion(self, key, *args):
        union = set()
        for rkey in (key,) + args:
            union.update(self._data.get(rkey, set()))
        return union

    @maybe_async
    def sismember(self, key, value):
        sval = self._data.get(key, set())
        return value in sval

    # Sorted set operations

    @maybe_async
    def zadd(self, key, **valscores):
        zval = self._data.setdefault(key, [])
        new_zval = [val for val in zval if val[1] not in valscores]
        for value, score in valscores.items():
            new_zval.append((score, value))
        new_zval.sort()
        self._data[key] = new_zval

    @maybe_async
    def zrem(self, key, value):
        zval = self._data.setdefault(key, [])
        new_zval = [val for val in zval if val[1] != value]
        self._data[key] = new_zval

    @maybe_async
    def zcard(self, key):
        return len(self._data.get(key, []))

    @maybe_async
    def zrange(self, key, start, stop, desc=False, withscores=False,
                score_cast_func=float):
        zval = self._data.get(key, [])
        stop += 1  # redis start/stop are element indexes
        if stop == 0:
            stop = None
        results = sorted(zval[start:stop],
                    key=lambda (score, _): score_cast_func(score))
        if desc:
            results.reverse()
        if withscores:
            return results
        else:
            return [v for k, v in results]

    # List operations
    @maybe_async
    def llen(self, key):
        return len(self._data.get(key, []))

    @maybe_async
    def lpop(self, key):
        if self.llen.sync(self, key):
            return self._data[key].pop(0)

    @maybe_async
    def lpush(self, key, obj):
        self._data.setdefault(key, []).insert(0, obj)

    @maybe_async
    def rpush(self, key, obj):
        self._data.setdefault(key, []).append(obj)
        return self.llen.sync(self, key) - 1

    @maybe_async
    def lrange(self, key, start, end):
        lval = self._data.get(key, [])
        if end >= 0 or end < -1:
            end += 1
        else:
            end = None
        return lval[start:end]

    @maybe_async
    def lrem(self, key, value, num=0):
        removed = [0]

        def keep(v):
            if v == value and (num == 0 or removed[0] < abs(num)):
                removed[0] += 1
                return False
            return True

        lval = self._data.get(key, [])
        if num >= 0:
            lval = [v for v in lval if keep(v)]
        else:
            lval.reverse()
            lval = [v for v in lval if keep(v)]
            lval.reverse()
        self._data[key] = lval
        return removed[0]

    # Expiry operations

    @maybe_async
    def expire(self, key, seconds):
        self.persist.sync(self, key)
        delayed = reactor.callLater(seconds, self.delete.sync, self, key)
        self._expiries[key] = delayed

    @maybe_async
    def persist(self, key):
        delayed = self._expiries.get(key)
        if delayed is not None and not delayed.cancelled:
            delayed.cancel()