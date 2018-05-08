from datetime import datetime

import bs4
from dateutil.parser import parse as dt_parse


def apply_instruction(elt, instruction):
    if callable(instruction):
        return instruction(elt)

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
                new_result = []
                for elt in result:
                    add = apply_instruction(elt, fn)
                    if isinstance(add, (list, map)):
                        new_result += add
                    else:
                        new_result.append(add)
                result = new_result
        else:
            for fn in fns:
                result = apply_instruction(result, fn)
        return result


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


def attr(attrname):
    """Use to pull an attribute into a scraped dictionary:

    dict_from_selectors({"url": ("a", attr("href"))})
    """
    return lambda elt: elt.attrs[attrname]


# def date(fmt=None, tz=None):
#     def get_date(arg):
#         if fmt:
#             return datetime.strptime(fmt, arg)
#         else:
#             return dt_parse(arg)

#     return get_date
def date(arg):
    return dt_parse(arg)
