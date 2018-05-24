from datetime import datetime, timedelta
import io
from itertools import takewhile
import os
import re
from urllib import parse

from cloud import aws_lambda
from scrape_utils import (attr, ch, scrape,
                          address, date, text, text_children, text_contains)
from shared import preprocess

import bs4
import pytz
import requests

from PyPDF2 import PdfFileReader

URL = "https://www.somervillema.gov/event-documents"
TIMEZONE = pytz.timezone("US/Eastern")


def file_name(url):
    return os.path.basename(parse.urlsplit(url).path)


# PDF Scraping
CasePattern = r"\s?((?:[\dA-Z]+-)+(?:[\dA-Z]+))"
PBCasePattern = r"(PB)" + CasePattern
ZBACasePattern = r"(ZBA)" + CasePattern


def get_pdf(url):
    pdf_in = io.BytesIO(requests.get(url).content)
    return PdfFileReader(pdf_in)


def case_year(case):
    m = re.match(r"[A-Z]+\s*(\d+)", case)
    year = m and m.group(1)
    return int(year) if year and year.isdigit() else 0


def get_cases(pdf, case_pattern=PBCasePattern):
    """Extremely crude approach to scraping cases from an agenda PDF.
    """
    if isinstance(pdf, str):
        pdf = get_pdf(pdf)

    for page in pdf.pages:
        matches = re.findall(case_pattern, page.extractText().replace("\n", ""))
        yield from [f"{auth} {case}" for auth, case in matches]


# Web scraping
def get_page(url):
    return bs4.BeautifulSoup(requests.get(url).content, "html.parser")


def get_event_details(event):
    address_defaults = {"city": "Somerville", "state": "MA", "zip": "02143"}
    details =  scrape(event, {
        "location": (".calendar-content__event-location", ch(text_children, "\n".join,
                                                             address(defaults=address_defaults))),
        "description": (".main-content .field-type-text-with-summary", ch(["p"], text, "\n".join)),
        "departments": ([".field-name-field-event-department li"], text),
        "contact": (".field-name-field-event-contact-name", [".field-items .field-item"], text),
        "image": (".field-content a img", attr("src")),
        "cost": ".calendar-content__price",
        "accessibility": ".calendar-content__accessibility-text"
    })
    return details


def url_for_page(i):
    return f"{URL}?page={i}"


def get_pages(make_url=url_for_page):
    """Lazily grabs event pages from the Somerville events site. Consumers should
    also be lazily evaluated, or else have some terminating condition;
    otherwise, this will bombard somervillema.gov with requests.

    """
    yield from ((url, get_page(url)) for url in map(make_url, range(50)))


def get_events(doc, url_base=URL, match=r"Planning Board|Zoning Board of Appeals"):
    def make_absolute(url):
        return parse.urljoin(url_base, url)

    def remove_prefix(title: str):
        return title[9:] if title.startswith("Download") else title

    match = re.compile(match)

    return scrape(doc,
                  ([".view-event-documents tbody tr", (".views-field-field-event-doc-event", text, match)],
                   {"title": (".views-field-field-event-doc-event", text, str.strip),
                    "url": (".views-field-field-event-doc-event a", attr("href"), make_absolute),
                    "start": (".date-display-single", attr("content"), date),
                    "documents": (["span.file a"], {"url": (attr("href"), make_absolute),
                                                    "file_title": (attr("href"), file_name),
                                                    "title": (text, remove_prefix)})
                   }))


def add_event_details(event):
    details = get_event_details(get_page(event["url"]))
    year = event["start"].year
    event.update(details)

    for doc in event["documents"]:
        if "Agenda" in doc["title"]:
            pattern = PBCasePattern if "Planning Board" in event["title"] else ZBACasePattern
            event["cases"] = [cn for cn in get_cases(doc["url"], pattern)
                              if year - case_year(cn) <= 4]  # hack!
            break

    event["region_name"] = "Somerville, MA"
    return event


def get_page_events(url, page):
    return map(add_event_details, get_events(page, url))


def get_all_events():
    for url, page in get_pages():
        yield from get_page_events(url, page)


def get_events_since(when: datetime):
    if not when.tzinfo:
        when = TIMEZONE.localize(when)

    yield from takewhile(lambda event: event["start"] > when, get_all_events())


@aws_lambda
@preprocess(TIMEZONE, timedelta(days=7))
def run(since):
    return {"events": list(get_events_since(since))}
