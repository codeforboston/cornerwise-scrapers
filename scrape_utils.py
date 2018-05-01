import bs4


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
