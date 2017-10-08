from os import path
import sys

from datetime import datetime, timedelta
import logging
import re
import pytz
from functools import partial
from bs4 import BeautifulSoup
from itertools import takewhile
import pytz

from cloud import aws_lambda
from shared import preprocess

from urllib.request import urlopen
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin


logger = logging.getLogger(__name__)
TIMEZONE = pytz.timezone("US/Eastern")
URL_HOST = "https://www.somervillema.gov"
URL_BASE = (f"{URL_HOST}/departments/ospcd/"
            "planning-and-zoning/reports-and-decisions/robots")
URL_FORMAT = URL_BASE + "?page={:1}"

HEARING_HOUR = 18
HEARING_MIN = 0

def to_under(s):
    "Converts a whitespace-separated string to underscore-separated."
    return re.sub(r"\s+", "_", s.lower())


def link_info(a, base=URL_BASE):
    return {"title": a.get_text().strip(),
            "url": urljoin(base, a["href"]).replace(" ", "%20")}


def get_date(d):
    return datetime.strptime(d, "%b %d, %Y")


def get_datetime(datestring, tzinfo=None):
    dt = datetime.strptime(datestring, "%m/%d/%Y - %I:%M%p")
    if tzinfo:
        return tzinfo.localize(dt)

    return dt


def get_links(elt):
    "Return information about the <a> element descendants of elt."
    return [link_info(a) for a in elt.find_all("a") if a["href"]]


# Field processors:
def dates_field(td):
    return get_date(default_field(td))


def datetime_field(td, tzinfo=None):
    return get_datetime(default_field(td), tzinfo)


def datetime_field_tz(tz):
    if isinstance(tz, str):
        tz = pytz.timezone(tz)
    return partial(datetime_field, tzinfo=tz)


def links_field(td):
    links = get_links(td)
    if links:
        return {"links": get_links(td)}


def default_field(td):
    return td.get_text().strip()


def optional(fn, default=None):
    def helper(td):
        try:
            val = fn(td)
            return default if val is None else val
        except:
            return default

    return helper


def get_td_value(td, attr=None, processors={}):
    processor = processors.get(attr, default_field)
    return processor(td)


def get_row_vals(attrs, tr, processors={}):
    return {
        attr: get_td_value(
            td, attr, processors=processors)
        for attr, td in zip(attrs, tr.find_all("td"))
    }


def col_names(table):
    tr = table.select("thead > tr")[0]
    return [th.get_text().strip() for th in tr.find_all("th")]


def find_table(doc):
    return doc.select("table.views-table")[0]


def get_data(doc, get_attribute=to_under, processors={}):
    table = find_table(doc)
    titles = col_names(table)
    attributes = [attribute_for_title(t) for t in titles]

    trs = table.find("tbody").find_all("tr")
    for i, tr in enumerate(trs):
        yield get_row_vals(attributes, tr, processors)


def event_title_for_case_number(case_number):
    if case_number.startswith("PB"):
        return "Planning Board"

    if case_number.startswith("ZBA"):
        return "Zoning Board of Appeals"


DEFAULT_EVENT_DESCRIPTIONS = {
    "Zoning Board of Appeals": ("The ZBA is the Special Permit Granting Authority for variances; appeals of decisions; Comprehensive Permit Petitions; and some Special Permit applications"),

    "Planning Board": ("The Planning Board is the Special Permit Granting Authority for special districts and makes recommendations to the Board of Aldermen on zoning amendments.")
}




# Give the attributes a custom name:
TITLES = {}


def attribute_for_title(title):
    """
    Convert the title (e.g., in a <th></th>) to its corresponding
    attribute in the output maps.
    """
    return TITLES.get(title, to_under(title))


# TODO: Return None or error if the response is not successful
def get_page(page=1, url_format=URL_FORMAT):
    "Returns the HTML content of the given Reports and Decisions page."
    url = url_format.format(page)
    f = urlopen(url)
    logger.info("Fetching page %i", page)
    html = f.read()
    f.close()
    return html


def detect_last_page(doc):
    anchor = doc.select("li.pager-last a")[0]
    m = re.search(r"[?&]page=(\d+)", anchor["href"])

    if m:
        return int(m.group(1))

    return 0


# Field

def get_links(elt, base=URL_BASE):
    "Return information about the <a> element descendants of elt."
    return [link_info(a, base) for a in elt.find_all("a") if a["href"]]


def staff_report_field(td, base=URL_BASE):
    links = sum((a.find_all("a") for a in td.find_all("a")), [])
    return links and {"links": [link_info(a, base) for a in links]}


def default_field(td):
    return td.get_text().strip()

field_processors = {
    "reports": staff_report_field,
    "decisions": links_field,
    "other": links_field,
    "first_hearing_date": optional(dates_field),
    "updated_date": datetime_field_tz(TIMEZONE)
}


def get_td_val(td, attr=None):
    processor = field_processors.get(attr, default_field)
    return processor(td)


def parse_addresses(number, street):
    number_sublists = re.split(r"\s*/\s*", number)
    street_sublists = re.split(r"\s*/\s*", street)

    for number, street in zip(number_sublists, street_sublists):
        number_range_match = re.match(r"(\d+)-(\d+)", number)

        if number_range_match:
            yield (number_range_match.group(1), street)
            yield (number_range_match.group(2), street)
        else:
            number_sublist = re.split(r",? and |,? & |, ", number)
            for number in number_sublist:
                yield (number, street)


def get_address_list(number, street):
    return ["{} {}".format(n, s) for (n, s) in parse_addresses(number, street)]


def find_cases(doc):
    """Takes a BeautifulSoup document, returns a list of maps representing the
    proposals found in the document.
    """
    cases = []

    for i, proposal in enumerate(get_data(doc, processors=field_processors)):
        try:
            addresses = get_address_list(proposal["number"], proposal["street"])
            proposal["all_addresses"] = addresses
            proposal["source"] = URL_BASE

            # Event:
            events = []
            event_title = event_title_for_case_number(proposal["case_number"]),
            event_description = DEFAULT_EVENT_DESCRIPTIONS.get(event_title)
            first_hearing = proposal.get("first_hearing_date")
            if first_hearing and event_title:
                first_hearing = first_hearing.replace(hour=HEARING_HOUR, minute=HEARING_MIN)
                events.append(
                    {"title": event_title,
                     "description": event_description,
                     "date": first_hearing,
                     "region_name": "Somerville, MA"})

            # For now, we assume that if there are one or more documents
            # linked in the 'decision' page, the proposal is 'complete'.
            # Note that we don't have insight into whether the proposal was
            # approved!
            proposal["complete"] = bool(proposal["decisions"])
            proposal["events"] = events
            cases.append(proposal)
        except Exception as err:
            tr_string = " | ".join(tr.stripped_strings)
            logger.error("Failed to scrape row %i: %s", i, tr_string)
            logger.error(err)
            continue
    return cases


def get_proposals_for_page(page):
    html = get_page(page)
    doc = BeautifulSoup(html, "html.parser")
    logger.info("Scraping page {num}".format(num=page))
    cases = find_cases(doc)

    return cases


def get_pages():
    """Returns a generator that retrieves Reports and Decisions pages and
    parses them as HTML.

    """
    i = 0
    last_page = None

    while True:
        try:
            # There's currently a bug in the Reports and Decisions page
            # that causes nonexistent pages to load page 1. They should
            # return a 404 error instead!
            html = get_page(i)
        except HTTPError as err:
            break

        except URLError as err:
            logger.warn("Failed to retrieve URL for page %d.", i,
                        err)
            break

        doc = BeautifulSoup(html, "html.parser")
        if last_page is None:
            last_page = detect_last_page(doc)

        yield doc

        i += 1

        if i > last_page:
            break


def get_cases(gen=None):
    "Returns a generator that produces cases."
    if not gen:
        gen = get_pages()

    for doc in gen:
        for case in find_cases(doc):
            yield case


def get_proposals_since(dt=None,
                        stop_at_case=None,
                        date_column="updated_date",):
    """Page through the Reports and Decisions page, scraping the proposals
    until the submission date is less than or equal to the given date.

    :param dt: If provided, stop scraping when the `date_column` is less
    than or equal to this datetime.

    :param stop_at_case: If provided, stop scraping when a case number
    matches this string

    :param date_column: Customize the name of the date column

    :returns: A list of dicts representing scraped cases.

    """
    if not dt.tzinfo:
        dt = TIMEZONE.localize(dt)

    def guard(case):
        return (not dt or case[date_column] > dt) and \
            (not stop_at_case or case["case_number"] != stop_at_case)

    all_cases = list(takewhile(guard, get_cases()))

    return all_cases


@aws_lambda
@preprocess(TIMEZONE)
def scrape(since):
    return {"cases": get_proposals_since(since)}
