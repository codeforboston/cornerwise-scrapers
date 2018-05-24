from datetime import datetime
import logging
import re
import os
from functools import partial
from bs4 import BeautifulSoup
from itertools import takewhile

import pytz
import requests

from cloud import aws_lambda
from shared import preprocess

from urllib.error import HTTPError, URLError
from urllib.parse import urljoin


logger = logging.getLogger(__name__)
TIMEZONE = pytz.timezone("US/Eastern")
URL_HOST = "https://www.somervillema.gov"
URL_BASE = (f"{URL_HOST}/departments/ospcd/"
            "planning-and-zoning/reports-and-decisions/robots")
URL_FORMAT = URL_BASE + "?page={:1}"

def to_under(s):
    "Converts a whitespace-separated string to underscore-separated."
    return re.sub(r"\s+", "_", s.lower())


def link_info(a, base=URL_BASE):
    return {"title": a.get_text().strip(),
            "url": urljoin(base, a["href"]).replace(" ", "%20"),
            "content_type": a.get("type", "").split(";", 1)[0]}


def get_datetime(datestring, tzinfo=None, pattern="%m/%d/%Y - %I:%M%p"):
    dt = datetime.strptime(datestring, pattern)
    if tzinfo:
        return tzinfo.localize(dt)

    return dt


get_date = partial(get_datetime, pattern="%b %d, %Y")


def get_links(elt):
    "Return information about the <a> element descendants of elt."
    return [link_info(a) for a in elt.find_all("a") if a["href"]]


# Field processors:
def dates_field(td, tzinfo=None):
    return get_date(default_field(td), tzinfo)


def datetime_field(td, tzinfo=None):
    return get_datetime(default_field(td), tzinfo)


def with_tz(fn, tz):
    if isinstance(tz, str):
        tz = pytz.timezone(tz)
    return partial(fn, tzinfo=tz)


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
        except Exception as err:
            logger.exception(f"Optional field failed with Exception:")
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
        yield i, tr, get_row_vals(attributes, tr, processors)


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
    response = requests.get(url_format.format(page))
    if response.status_code == 200:
        return response.content


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


def case_numbers(text, prefs=["PB", "ZBA"]):
    prefs_group = "|".join(prefs)
    return re.findall(rf"(?:{prefs_group})" r"\s*(?:\d{4}(?:-[A-Z]?\d+)+)", text)


def format_case_number(text):
    text = re.sub(r"--+", "-", text)
    m = re.match(r"([A-Z]+)\s*", text)

    return f"{m.group(1)} {text[m.end():]}"


def default_field(td):
    return td.get_text().strip()


field_processors = {
    "reports": links_field,
    "decisions": links_field,
    "other": links_field,
    "first_hearing_date": optional(with_tz(dates_field, TIMEZONE)),
    "updated_date": with_tz(datetime_field, TIMEZONE)
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

    for i, tr, proposal in get_data(doc, processors=field_processors):
        try:
            addresses = get_address_list(proposal["number"], proposal["street"])
            proposal["all_addresses"] = addresses
            proposal["source"] = URL_BASE

            all_cases = list(map(format_case_number, case_numbers(proposal["case_number"])))
            proposal["case_number"] = all_cases[0]
            if len(all_cases) > 1:
                proposal["case_numbers"] = all_cases

            proposal["documents"] = []
            for k in ["reports", "decisions", "other"]:
                if proposal[k]:
                    for link in proposal[k].get("links", []):
                        _, ext = os.path.splitext(link["url"])
                        if not ext:
                            continue
                        link["tags"] = [k]
                        proposal["documents"].append(link)
                del proposal[k]

            del proposal["number"]
            del proposal["street"]

            cases.append(proposal)
        except Exception as err:
            tr_string = " | ".join(tr.stripped_strings)
            logger.exception("Failed to scrape row %i: %s", i, tr_string)
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
    for doc in (gen or get_pages()):
        yield from find_cases(doc)


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

    if dt:
        guard = lambda case: case[date_column] > dt
    elif stop_at_case:
        guard = lambda case: case["case_number"] != stop_at_case

    all_cases = list(takewhile(guard, get_cases()))

    return all_cases


@aws_lambda
@preprocess(TIMEZONE)
def scrape(since):
    return {"cases": get_proposals_since(since)}
