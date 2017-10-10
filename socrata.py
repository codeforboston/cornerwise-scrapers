from urllib import parse
from urllib.request import Request, urlopen
import json


accepts = {
    "json": "application/json",
    "xml":  "application/xml"
}

def make_request(domain, resource_id, token, soql=None, where=None,
                 select=":updated_at, *", fmt="json", offset=None, params={}):
    params = dict(params) # make a copy
    if soql:
        params["$query"] = soql
    elif where:
        params["$where"] = where
        if select:
            params["$select"] = select
    qs = "?" + parse.urlencode(params)
    url = f"https://{domain}/resource/{resource_id}.{fmt}{qs}"
    print(url)

    return Request(url, None, {"Accept": accepts[fmt],
                               "X-App-Token": token})


def json_request(*args, **kwargs):
    req = make_request(*args, **kwargs)
    with urlopen(req) as f:
        return json.loads(f.read().decode("utf-8"))

