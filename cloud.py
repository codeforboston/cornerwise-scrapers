from datetime import datetime
import glob
import json
import logging
import os
import sys
import traceback

from urllib.parse import parse_qsl

logger = logging.getLogger(__name__)


try:
    # Add zipped packages to the same directory where this file lives:
    zip_paths = glob.glob(os.path.join(os.path.dirname(__file__), "*.zip"))
    sys.path += zip_paths
except:
    pass


class Request(object):
    def __init__(self,
                 method="GET",
                 headers=None,
                 query=None,
                 path="/",
                 body=None,
                 bodytext=None):
        self._headers = headers or {}
        self._query = query or {}
        self._post_params = self._process_post_body()
        self._path = path
        self._bodytext = bodytext
        self._body = body
        self._method = method

    @property
    def content_type(self):
        self._headers.get("content-type", "application/x-www-form-urlencoded")

    def read_body(self):
        if not self._bodytext:
            self._bodytext = self._body.read()
        return self._bodytext

    def _process_post_body(self):
        if self.content_type == "application/x-www-form-urlencoded":
            return dict(parse_qsl(self.read_body()))

        return {}

    @property
    def headers(self):
        return self._headers

    @property
    def GET(self):
        return self._query

    @property
    def POST(self):
        return self._post_params

    def __getitem__(self, k):
        return self._post_params.get(k) or self._query.get(k)


def make_azure_request(env):
    headers = {}
    query = {}
    for key, val in env.items():
        if key.startswith("REQ_HEADERS"):
            headers[key[12:].lower()] = val
        elif key.startswith("REQ_QUERY"):
            query[key[10:].lower()] = val

    inpath = env.get("req")
    infile = open(inpath, "r") if inpath else None

    return Request(
        method=env["REQ_METHOD"].upper(),
        headers=headers,
        query=query,
        path=env["REQ_HEADERS_X-ORIGINAL-URL"],
        body=infile,)


def json_serialize(x):
    if isinstance(x, datetime):
        return x.isoformat()

    return str(x)


def output(req, resp):
    with open(os.environ["RES"]) as out:
        out.write(json.dumps(resp, default=json_serialize))


def body_output(req, s, status=200, content_type="text/plain"):
    output(req, {
        "status": status,
        "body": s,
        "headers": {
            "content-type": content_type
        }
    })


def redirect_output(req, location):
    output(req, {"status": 302, "headers": {"location": location}})


def redirect(location):
    return lambda req: redirect_output(req, location)


def make_lambda_request(event, context):
    return Request(
        method=event["httpMethod"],
        headers=event["headers"],
        query=event["queryStringParameters"],
        path=event["path"],
        body=event["body"])


def lambda_response(body, status=200, content_type="text/plain"):
    return {
        "statusCode": status,
        "body": body,
        "headers": {
            "content-type": content_type
        }
    }


def azure(fn):
    """
    Function decorator that calls fn immediately with environment variables
    processed into a Request object.
    """
    req = make_azure_request(os.environ)
    try:
        response = fn(req)

        if isinstance(response, str):
            body_output(req, response)
        elif isinstance(response, dict):
            body_output(req, response, content_type="application/json")
        elif callable(response):
            response(req)
    except Exception as exc:
        body_output(req, traceback.format_exc(), status=500)

    return fn


def aws_lambda(fn):
    """Function decorator for a handler function running on AWS Lambda.

    :param fn: function taking a request object
    """
    handler_name = f"{fn.__module__}.{fn.__name__}"
    def do_run(event, context):
        req = make_lambda_request(event, context)

        try:
            response = fn(req)
        except Exception as exc:
            logger.exception(f"Exception thrown in handler: {handler_name}")

            return lambda_response(
                {"error": f"Exception in {handler_name}"},
                status=500,
                content_type="application/json"
            )

        if isinstance(response, str):
            return lambda_response(response)
        if isinstance(response, dict):
            return lambda_response(
                json.dumps(response, default=json_serialize),
                content_type="application/json")
        if callable(response):
            return response(req)

    do_run.__name__ = fn.__name__
    do_run.__module__ = fn.__module__
    return do_run


def cloud_fn(fn):
    if "AWS_REGION" in os.environ:
        return aws_lambda(fn)
    # TODO: Improve testing for whether we're in Azure.
    if True:
        return azure(fn)
