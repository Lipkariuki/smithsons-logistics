"""Request-local reuse of immutable source reads; never cache financial decisions.

No process/global result cache. A new request always reads/revalidates its source.
Only pure workbook parsing and immutable archive lookups may use this decorator.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from functools import wraps

_reads = ContextVar('monthly_reporting_reads', default=None)


@contextmanager
def reporting_read_scope():
    if _reads.get() is not None:
        yield
        return
    token = _reads.set({})
    try:
        yield
    finally:
        _reads.reset(token)


def request_read(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        cache = _reads.get()
        if cache is None:
            return function(*args, **kwargs)
        key = (function.__module__, function.__qualname__, args, tuple(sorted(kwargs.items())))
        if key not in cache:
            cache[key] = function(*args, **kwargs)
        # Callers may append audit details; never let them poison another use.
        return deepcopy(cache[key])
    return wrapped
