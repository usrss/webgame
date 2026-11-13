"""Cache-backed rate limiting (Phase 2).

A tiny decorator built on Django's cache framework: no new dependency. It uses
``cache.add`` (atomic "set if absent") plus ``cache.incr``, so concurrent
requests from the same user cannot both slip under the limit.

NOTE: the default ``LocMemCache`` is per-process, so with several web workers a
user effectively gets the limit *per worker*. Production needs a shared cache
(Redis/Memcached) - Phase 6 handles that.
"""

from __future__ import annotations

import math
import time
from functools import wraps

from django.core.cache import cache
from django.shortcuts import render

# Only these request methods count as "attempts"; loading a form doesn't.
COUNTED_METHODS = ("POST",)


def ratelimit(scope: str, limit: int, window_seconds: int):
    """Limit counted requests from one user (or IP) to *limit* per window.

    Keys are namespaced ``rl:<scope>:<identity>`` where identity is the user id
    for authenticated requests and the client IP otherwise. Over the limit, the
    wrapped view is not called: a 429 page is returned with a ``Retry-After``
    header telling the client when the current window ends.
    """

    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if request.method not in COUNTED_METHODS:
                return view_func(request, *args, **kwargs)

            identity = (
                request.user.pk
                if request.user.is_authenticated
                else request.META.get("REMOTE_ADDR", "anonymous")
            )
            count_key = f"rl:{scope}:{identity}"
            start_key = f"rl:{scope}:{identity}:start"
            now = time.time()

            if cache.add(count_key, 1, window_seconds):
                count = 1
                cache.add(start_key, now, window_seconds)
            else:
                try:
                    count = cache.incr(count_key)
                except ValueError:
                    # Counter expired between add and incr: start a new window.
                    cache.set(count_key, 1, window_seconds)
                    cache.set(start_key, now, window_seconds)
                    count = 1

            if count > limit:
                window_start = cache.get(start_key) or now
                retry_after = max(1, int(math.ceil(window_seconds - (now - window_start))))
                response = render(
                    request,
                    "game/rate_limited.html",
                    {"retry_after": retry_after},
                    status=429,
                )
                response["Retry-After"] = str(retry_after)
                return response

            return view_func(request, *args, **kwargs)

        return wrapper

    return decorator
