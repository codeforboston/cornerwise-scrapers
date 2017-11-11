import os
from urllib import request, parse

import bs4


URL = "https://www.somervillema.gov/events?field_event_department_target_id=133&field_event_type_value=All&field_city_event_value=1"


# def make_page_lister(tag, css_classes, attrs):
#     def match_items(elt):
def apply_instruction(elt, instruction):
    if isinstance(instruction, str):
        return elt.select_one(instruction)

    if isinstance(instruction, list):
        return elt.select(instruction[0])

    if isinstance(instruction, dict):
        return dict_from_selectors(elt, instruction)

    if isinstance(instruction, tuple):
        (selector, *fns) = instruction
        result = apply_instruction(elt, selector)
        if isinstance(result, list):
            for fn in fns:
                result = map(fn, result)
        else:
            for fn in fns:
                result = fn(result)
        return result


def dict_from_selectors(elt, selectors):
    result = {}
    for prop, instruction in selectors.items():
        applied = apply_instruction(elt, instruction)
        if isinstance(applied, map):
            result[prop] = list(applied)
        elif isinstance(applied, bs4.Tag):
            result[prop] = applied.text
        else:
            result[prop] = applied
    return result


def text(elt):
    return elt.text


def text_children(elt):
    pieces = (child.strip() for child in elt.children if isinstance(child, str))
    return list(filter(None, pieces))


def attr(attrname):
    return lambda elt: elt.attrs[attrname]


def get_event_details(event):
    return dict_from_selectors(event, {
        "title": "h3",
        "url": ("h3 a", attr("href")),
        "date": (".article-content--event-time span", attr("content")),
        "description": ([".views-field-body p"], text),
        "image": (".field-content a img", attr("src"))
    })


def get_event_page_details(event):
    return dict_from_selectors(event, {
        "location": (".calendar-content__event-location", text_children),
        "full_description": (".field-name-body", text)
    })


def get_full_details(event_url):
    url = parse.urljoin(URL, event_url)
    with request.urlopen(url) as event_page:
        return get_event_page_details(bs4.BeautifulSoup(event_page.read(), "html.parser"))


def get_items(doc):
    for event in doc.select("article"):
        details = get_event_details(event)
        details.update(get_full_details(details["url"]))
        yield details


def get_events(url=URL):
    with request.urlopen(url) as events_page:
        return get_items(bs4.BeautifulSoup(events_page.read(), "html.parser"))
