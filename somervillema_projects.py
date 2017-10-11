from datetime import datetime
from decimal import Decimal
import pytz

import json
import os
import re
from urllib.error import HTTPError

from cloud import aws_lambda
from shared import preprocess
import socrata


SOCRATA_TOKEN = os.environ["SOCRATA_TOKEN"]
TIMEZONE = pytz.timezone("US/Eastern")


copy_keys = {
    "name":           "project",
    "description":    "project_description",
    "justification":  "project_justification",
    "department":     "department",
    "category":       "type",
    "funding_source": "funding_source",
}


def process_json(project):
    d = {"region_name": "Somerville, MA"}
    for dk, pk in copy_keys.items():
        d[dk] = project.get(pk)
    try:
        location = project["address"]
        if not location["needs_recoding"]:
            d["location"] = {
                "lat": location["latitude"],
                "long": location["longitude"]
            }
        address = json.loads(location["human_address"])
        d["address"] = {
            "street_address": address["address"],
            "city": address["city"],
            "state": address["state"],
            "zip": address["zip"],
        }
    except KeyError:
        d["address"] = None

    d["approved"] = bool(re.match(r"approved", project["status"], re.I))
    d["status"] = project["status"]

    budget_keys = ((k, re.match(r"^_(\d+)$", k)) for k in project.keys())
    d["budget"] = {m.group(1): int(project[k])
                   for k, m in budget_keys if m}
    # d["updated"] = datetime.fromtimestamp(project[":updated_at"], TIMEZONE)\
    #                        .isoformat()

    return d


def get_projects_since(since):
    timestamp = int(since.timestamp())
    response = socrata.json_request("data.somervillema.gov", "wz6k-gm5k",
                                    SOCRATA_TOKEN)

    return [process_json(p) for p in response]


@aws_lambda
@preprocess(TIMEZONE)
def scrape(since):
    return {"projects": get_projects_since(since)}


def dont():
    class SomervilleProjectImporter(Importer):
        domain = "data.somervillema.gov"
        resource_id = "wz6k-gm5k"


        constant_fields = {
            "region_name": "Somerville, MA"
        }

        address_key = "address"

        def process(self, json, project):
            project["approved"] = bool(re.match(r"approved", json["status"],
                                                re.I))
            project["status"] = json["status"]

            budget_keys = ((k, re.match(r"^_(\d+)$", k)) for k in json.keys())
            project["budget"] = {int(m.group(1)): Decimal(json[k])
                                for k, m in budget_keys if m}
            project["updated"] = datetime.fromtimestamp(json[":updated_at"],
                                                        pytz.utc)

