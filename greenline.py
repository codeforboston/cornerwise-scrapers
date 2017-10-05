"""Scrapes the official Green Line Extension site to find the posting for the
next scheduled meeting.
"""
from datetime import datetime, time
import re
from urllib.request import urlopen

from bs4 import BeautifulSoup, NavigableString
import pytz

from cloud import aws_lambda


TIMEZONE = pytz.timezone("US/Eastern")

def get_doc():
    with urlopen("http://greenlineextension.org") as u:
        return BeautifulSoup(u.read(), "html.parser")


def find_text_elem(elem, regex, tags={"tr"}):
    regex = re.compile(regex)
    def finder(desc_elem):
        return bool(regex.match(desc_elem.text.strip())) and desc_elem.name in tags
    return elem.find(finder)


def time_match(time_range):
    match = re.search(re.compile(r"(\d\d?):(\d\d)( am|pm)?\s+to\s+(\d\d?):(\d\d) (am|pm)", re.I), time_range)
    start_hour = int(match.group(1))
    start_minute = int(match.group(2))
    start_offset = 12 if (match.group(3) or match.group(6)).lower() == "pm" else 0

    end_hour = int(match.group(4))
    end_minute = int(match.group(5))
    end_offset = 12 if match.group(6).lower() == "pm" else 0

    return (time(start_hour + start_offset, start_minute),
            time(end_hour + end_offset, end_minute))


def scrape_events(doc=None):
    tr = find_text_elem(doc or get_doc(), re.compile(r"^upcoming meetings$", re.I))
    schedule_row = tr.find_next_sibling("tr")
    name_when, desc, where = schedule_row.find_all("p")[0:3]

    name, day, timerange = [d for d in name_when.descendants if isinstance(d, NavigableString)]

    day = datetime.strptime(day.strip(), "%B %d, %Y")

    (start_time, end_time) = time_match(timerange)

    start_datetime = TIMEZONE.localize(datetime.combine(day, start_time))
    end_datetime = TIMEZONE.localize(datetime.combine(day, end_time))
    duration = (end_datetime - start_datetime).total_seconds()
    hours = int(duration/3600)
    minutes = int(duration%3600/60)

    place_name, address = [d for d in where.descendants if isinstance(d, NavigableString)]
    street_address, city, state = address.rsplit(",", 2)

    return [
        {
            "title": name,
            "description": desc.text.strip(),
            "start": start_datetime.isoformat(),
            "duration": f"{hours:0>2}:{minutes:0>2}",
            "region_name": "Somerville, MA",
            "address": {
                "name": place_name.strip(),
                "street_address": street_address.strip(),
                "city": city.strip(),
                "state": state.strip()
            }
        }
    ]


@aws_lambda
def handler(req):
    return {"events": scrape_events()}
