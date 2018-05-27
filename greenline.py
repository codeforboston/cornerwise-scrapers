"""Scrapes the official Green Line Extension site to find the posting for the
next scheduled meeting.
"""
from datetime import datetime, time, timedelta
import re
from urllib.request import urlopen

from bs4 import BeautifulSoup, NavigableString
from dateutil.parser import parse
import pytz

from cloud import aws_lambda


TIMEZONE = pytz.timezone("US/Eastern")

def get_doc():
    with urlopen("http://greenlineextension.org") as u:
        return BeautifulSoup(u.read(), "html.parser")


def find_text_elem(elem, regex, tags={"tr"}):
    regex = re.compile(regex)
    def finder(desc_elem):
        return regex.match(desc_elem.text.strip()) and desc_elem.name in tags
    return elem.find(finder)


time_range_pattern = re.compile(
    r"(\d\d?)(?::(\d\d))?(?:\s*([ap]\.?m\.?))?((?: to | *- *)(\d\d?)(?::(\d\d))?)?(?: *([ap]\.?m\.?))", re.I)

def match_time_range(text):
    match = time_range_pattern.search(text)
    if match:
        start_offset = 12 if (match.group(3) or match.group(7) or "").lower() == "pm" else 0
        start_time = time(int(match.group(1)) % 12 + start_offset,
                          int(match.group(2) or "0"))

        end_time = None
        if match.group(3):
            end_offset = 12 if (match.group(7) or "").lower() == "pm" else 0
            end_time = time(int(match.group(5)) % 12 + end_offset,
                            int(match.group(6) or "0"))

        return start_time, end_time

    return None, None


def process_event(elt):
    lines = [d.strip() for d in elt.descendants
             if isinstance(d, NavigableString) and d.strip()]
    for i, line in enumerate(lines):
        try:
            date = parse(lines[i])
            break
        except ValueError:
            continue

    date_line = i
    start_time, end_time = match_time_range(lines[date_line+1])

    start_datetime = TIMEZONE.localize(datetime.combine(date, start_time))
    try:
        end_datetime = TIMEZONE.localize(datetime.combine(date, end_time))
        duration = end_datetime - start_datetime
        hours = int(duration.total_seconds()/3600)
        minutes = int((duration.total_seconds % 3600)/60)
    except TypeError:
        hours, minutes = 1, 30

    locale_match = re.match(r"(.*), ([A-Z]{2}),? (\d{5})", lines[-1])

    return {
        "title": lines[0],
        "description": " ".join(lines[1:date_line]),
        "start": start_datetime.isoformat(),
        "duration": f"{hours}:{minutes:0>2}",
        "region_name": "Somerville, MA",
        "address": {
            "name": ", ".join(map(str.strip, lines[date_line+2:-2])),
            "street_address": lines[-2],
            "city": locale_match.group(1).strip(),
            "state": locale_match.group(2)
        }
    }


def find_meetings(doc):
    head = find_text_elem(doc, re.compile(r"^upcoming meetings$", re.I),
                          {"strong"})
    return head.find_parent("tr")


def scrape_events(doc=None):
    tr = find_meetings(doc or get_doc())
    schedule_row = tr.find_next_sibling("tr")
    event_elements = schedule_row.find_all("p")

    return [
        process_event(event_element) for event_element in event_elements
    ]


@aws_lambda
def handler(req):
    return {"events": scrape_events()}
