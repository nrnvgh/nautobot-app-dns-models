"""Marker distinguishing this app's own writes to system-managed records from user writes.

A catalog zone (RFC 9432) contains only records this app creates and maintains, so the guards in
`DNSRecord.clean()` and `DNSRecord.delete()` reject every write to them. The sync code that
legitimately owns those records needs a way to identify itself, and neither `full_clean()` nor
`QuerySet.delete()` accepts custom keyword arguments, so the marker travels out of band.

The flag is a `contextvars.ContextVar` rather than a thread-local, following
`nautobot.dcim.component_creation.SkipAutoComponentCreation`, so it is scoped per asyncio task and
per Celery invocation. A value set in one OS thread is not visible in a separately spawned thread,
so code fanning work out to a thread pool must enter the block inside each worker.
"""

import contextlib
import contextvars

_system_write_flag = contextvars.ContextVar("nautobot_dns_models_system_write", default=False)


def system_write_in_progress():
    """Return whether the calling context is inside a `system_write()` block."""
    return _system_write_flag.get()


@contextlib.contextmanager
def system_write():
    """Mark records written inside this block as maintained by the app rather than by a user."""
    token = _system_write_flag.set(True)
    try:
        yield
    finally:
        _system_write_flag.reset(token)
