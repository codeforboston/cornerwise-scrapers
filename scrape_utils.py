from datetime import datetime
import re

import bs4
from dateutil.parser import parse as dt_parse
import pytz


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
        (selector, *fns) = instruction
        result = apply_instruction(elt, selector)
        if isinstance(result, list):
            for fn in fns:
                new_result = []
                for elt in result:
                    add = apply_instruction(elt, fn)
                    if isinstance(add, (list, map)):
                        new_result += add
                    else:
                        new_result.append(add)
                result = new_result
        elif result:
            for fn in fns:
                result = apply_instruction(result, fn)
        return result

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
            result[prop] = applied.text
        else:
            result[prop] = applied
    return result


def text(elt):
    return elt.text


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


def either(*fns):
    return lambda elt: any(fn(elt) for fn in fns)
