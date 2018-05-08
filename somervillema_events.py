import os
import re
from urllib import parse



URL = "https://www.somervillema.gov/events?field_event_department_target_id=133&field_event_type_value=All&field_city_event_value=1"
from scrape_utils import dict_from_selectors, date, text, text_contains

import bs4
import requests



URL = "https://www.somervillema.gov/event-documents"









# Web scraping
def get_page(url):
    return bs4.BeautifulSoup(requests.get(url).content, "html.parser")


def get_event_details(event):
    return dict_from_selectors(event, {
        "location": ".calendar-content__event-location",
        "description": (".main-content .field-type-text-with-summary", ["p"], text),
        "departments": ([".field-name-field-event-department li"], text),
        "image": (".field-content a img", attr("src")),
        "cost": ".calendar-content__price",
        "accessibility": ".calendar-content__accessibility-text"
    })


def get_items(doc, url_base=URL, match=r"Planning Board|Zoning Board of Appeals"):
    def make_absolute(url):
        return parse.urljoin(url_base, url)

    match = re.compile(match)

    return dict_from_selectors(doc, {
        "events": ([".view-event-documents tbody tr", (".views-field-field-event-doc-event", text, match)],
                   {"title": (".views-field-field-event-doc-event", text, str.strip),
                    "url": (".views-field-field-event-doc-event a", attr("href"), make_absolute,
                            get_page, get_event_details),
                    "date": (".date-display-single", attr("content"), date),
                    "agenda": ("span.file a", attr("href"), make_absolute)})
    })


def get_events(url=URL):
    response = requests.get(url)
    return get_items(bs4.BeautifulSoup(response.content, "html.parser"))
