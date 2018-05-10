from collections import defaultdict
from datetime import datetime
from functools import reduce
import re

import bs4
from dateutil.parser import parse as dt_parse
import pytz
import usaddress


def apply_tuple(elt, instruction):
    (selector, *rest) = instruction

    result = elt
    if isinstance(elt, list):
        new_result = []
        for member in elt:
            add = apply_instruction(member, selector)
            if isinstance(add, (list, map)):
                new_result += add
            else:
                new_result.append(add)
        result = new_result
    elif elt:
        result = apply_instruction(elt, selector)

    return apply_tuple(result, rest) if rest else result


def apply_instruction(elt, instruction):
    if callable(instruction):
        return instruction(elt)

    if isinstance(instruction, str):
        return elt.select_one(instruction)

    if isinstance(instruction, list):
        instruction, *filters = instruction
        return [match for match in elt.select(instruction)
                if all(apply_instruction(match, filt) for filt in filters)]

    if isinstance(instruction, dict):
        return dict_from_selectors(elt, instruction)

    if isinstance(instruction, tuple):
        return apply_tuple(elt, instruction)

    if getattr(instruction, "search"):
        return instruction.search(elt)


def dict_from_selectors(elt: bs4.element.Tag, selectors: dict):
    """Generate a dictionary by specifying keys and the CSS selectors to
    retrieve information from the element.

    :param elt: the context for the CSS selectors
    :param selectors: a dictionary mapping output keys to instructions. The
    instructions can be strings (selectors), tuples of (selector, fns...)
    """
    result = {}
    for prop, instruction in selectors.items():
        applied = apply_instruction(elt, instruction)
        if isinstance(applied, map):
            result[prop] = list(applied)
        elif isinstance(applied, bs4.Tag):
            result[prop] = applied.text.strip()
        else:
            result[prop] = applied
    return result


scrape = apply_instruction


def text(elt):
    return elt.text


def stripped_text(elt):
    return elt.text.strip()


def text_children(elt):
    pieces = (child.strip() for child in elt.children if isinstance(child, str))
    return list(filter(None, pieces))


def attr(attrname, val=None):
    """
    With one argument, pulls an attributes into a scraped dictionary:

    dict_from_selectors({"url": ("a", attr("href"))})

    With two arguments, returns an element filter that
    """
    if val:
        if getattr(val, "match", None):
            return lambda elt: val.match(elt.attrs.get("attrname", ""))
        else:
            return lambda elt: elt.attrs.get("attrname") == val

    return lambda elt: elt.attrs.get(attrname, "")


def date(arg=None, tz=None):
    if tz and not arg:
        return lambda x: date(x, tz)

    if isinstance(arg, bs4.Tag):
        arg = stripped_text(arg)

    if tz:
        dt = dt_parse(arg, ignoretz=True)
        return pytz.timezone(tz).localize(dt)

    return dt_parse(arg)


def text_contains(arg):
    return lambda elt: arg in elt.text


def text_matches(patt):
    if isinstance(patt, str):
        patt = re.compile(patt)

    return lambda elt: re.search(patt, elt.text)


children = bs4.Tag.children.fget


def either(*fns):
    return lambda elt: any(fn(elt) for fn in fns)


def ch(*fns):
    "Chain together some functions."
    return lambda elt: reduce((lambda x, fn: apply_instruction(x, fn)), fns, elt)


def to_under(s):
    "Converts a whitespace-separated string to underscore-separated."
    return re.sub(r"\s+", "_", s.lower())


def col_names(table):
    tr = table.select("thead > tr")[0]
    return [th.get_text().strip() for th in tr.find_all("th")]


def tabular(field_processors={}, convert_column=to_under, index=None):
    def process_table(elt):
        table = elt if elt.name == "table" else elt.find("table")
        columns = [convert_column(c) for c in col_names(table)]
        rows = table.find("tbody").find_all("tr")

        data = ({col_name: apply_instruction(cell, field_processors.get(col_name, stripped_text))
                 for col_name, cell in zip(columns, row.find_all("td"))}
                for row in rows)
        if index:
            return {datum[index]: datum for datum in data}
        else:
            return list(data)

    if isinstance(field_processors, bs4.Tag):
        return process_table(field_processors)

    return process_table


def address(text=None, defaults={}):
    if not text and defaults:
        return lambda elt: address(elt, defaults)

    if isinstance(text, bs4.Tag):
        text = text.text

    tagged, _ = usaddress.tag(text)
    tagged = defaultdict(str, tagged)
    street_address = "{AddressNumber} {StreetName} {StreetNamePostType}".format(**tagged)
    occupancy = "{a[Recipient]}\n{a[OccupancyIdentifier]} {a[OccupancyType]}".format(a=tagged)
    place = tagged["Place"]
    if "\n" in place:
        occupancy_name, place = place.rsplit("\n", 1)
        occupancy += f" {occupancy_name}"
    occupancy = re.sub(r"(^\s+|(?<=\s)\s+|\s+$)", "", occupancy)
    return {
        "name": occupancy,
        "city": place or defaults["city"],
        "state": tagged.get("Statename", defaults["state"]),
        "zip": tagged.get("ZipCode", defaults["zip"])
    }
