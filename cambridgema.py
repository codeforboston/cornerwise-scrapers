from datetime import datetime, timedelta
import os
import re

import pytz
from dateutil.parser import parse as date_parse

from cloud import aws_lambda
from shared import preprocess
import socrata


copy_keys = {
    "case_number": "plan_number",
    "status": "status",
    "summary": "summary_for_publication"
}

remap_attributes = {
    "Legal Notice": "description",
    "Type": "type",
    "Reason": "reason_for_petition_other"
}

SOCRATA_TOKEN = os.environ["SOCRATA_TOKEN"]
TIMEZONE = pytz.timezone("US/Eastern")
REGION_NAME = "Cambridge, MA"

def under_to_title(s):
    return " ".join(word.capitalize() for word in re.split(r"_+", s))


def no_data(s):
    return re.match(r"(n/?a|no change|same)", s, re.I)


def match_complete(s):
    return bool(re.match(r"(approved|denied|withdrawn)", s, re.I))


def process_json(pjson):
    """
    Process a single proposal into a JSON.
    """
    proposal = {}

    for kp, kj in copy_keys.items():
        if kj in pjson:
            proposal[kp] = pjson[kj]

    proposal["region_name"] = "Cambridge, MA"
    proposal["source"] = "https://data.cambridgema.gov"

    updated_datestr = pjson.get("decisiondate",
                                pjson["applicationdate"])
    updated_naive = date_parse(updated_datestr)
    proposal["updated_date"] = TIMEZONE.localize(updated_naive)
    proposal["complete"] = match_complete(pjson["status"])
    proposal["description"] = pjson.get("reason_for_petition_other", "")

    if "location" in pjson and not pjson["location"]["needs_recoding"]:
        location = pjson["location"]
        try:
            human_address = json.loads(location["human_address"])
            proposal["all_addresses"] = [human_address["address"].title()]
            proposal["location"] = {
                "lat": float(location["longitude"]),
                "long": float(location["latitude"])
            }
        except:
            proposal["location"] = None

    proposal["attributes"] = [(pk, pjson.get(k)) for pk, k in
                              remap_attributes.items()]

    return proposal


def get_proposals_since(since):
    soql = ("SELECT * WHERE applicationdate >= "
            "'{dt}' OR decisiondate >= '{dt}'")\
            .format(dt=since.isoformat())
    response = socrata.json_request("data.cambridgema.gov",
                                    "urfm-usws", SOCRATA_TOKEN, soql=soql)
    return [process_json(c) for c in response]


@aws_lambda
@preprocess(TIMEZONE)
def scrape(since):
    return {"cases": get_proposals_since(since)}
