from datetime import datetime, timedelta, tzinfo

import pytz


def preprocess(timezone):
    """Decorator that returns a function that takes a Request-like object with a
    'since' parameter of the form YYYYmmdd and calls the wrapped function with
    a datetime.

    """
    if not isinstance(timezone, tzinfo):
        timezone = pytz.timezone(timezone)

    def wrapper_fn(view_fn):
        def wrapped(req):
            since = req["since"]
            if since:
                since = timezone.localize(datetime.strptime(since, "%Y%m%d"))
            else:
                now = pytz.utc.localize(datetime.utcnow()).astimezone(timezone)
                since = now - timedelta(days=30)

            return view_fn(since)

        wrapped.__name__ = view_fn.__name__
        return wrapped

    return wrapper_fn
