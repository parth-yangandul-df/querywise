"""Shared SlowAPI rate-limiter instance.

Defined here (not in main.py) to avoid circular imports when endpoints
need to import the limiter for decorator usage.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
