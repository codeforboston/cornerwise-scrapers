"""Functions for extracting document attributes from its plaintext
contents.
"""

from collections import OrderedDict
import re

from dateutil.parser import parse as dt_parse
import pytz

from .s3doc import S3Doc
from .utils import pushback_iter

EMPTY_LINE = re.compile(r"\s*\n$")
PROPERTY_PATTERN = re.compile(r"^([a-z&/()]+(\s+[a-z&/()]+)*): (.*)(\n|$)", re.I)


def properties(lines):
    properties = {}
    last_property = None

    for line in lines:
        m = PROPERTY_PATTERN.match(line)

        if m:
            properties[m.group(1)] = m.group(3)
            last_property = m.group(1).strip()
        elif EMPTY_LINE.match(line):
            last_property = None
        elif last_property:
            properties[last_property] += " " + line.strip()

    return properties


def paragraphize(lines):
    ps = []
    current_p = []

    for line in lines:
        if EMPTY_LINE.match(line):
            ps.append(current_p)
            current_p = []
        else:
            current_p.append(line.strip())

    ps.append(current_p)

    return [" ".join(p) for p in ps if p]


def make_matcher(patt, group=0, value=None, fn=None):
    if isinstance(patt, str):
        patt = re.compile(patt)

    def matcher(line):
        m = patt.search(line)

        if m:
            v = m.group(group) if group else value or m.group(0)

            return fn(v) if (fn and v) else v

        return None

    return matcher


def skip_match(patt, n=0):
    if isinstance(patt, str):
        patt = re.compile(patt)

    def skipper(line):
        if re.match(patt, line):

            def skip(inlines):
                for i in range(n):
                    next(inlines)

            return skip

    return skipper


def subsection_matcher(line):
    if re.match(r"^[0-9]+\.$", line):
        subsection_patt = re.compile(r"^([a-z]+(\s+[a-z]+)*):", re.I)

        def get_subsection_name(in_lines):
            for line in in_lines:
                m = subsection_patt.match(line)
                if m:
                    if isinstance(in_lines, pushback_iter):
                        in_lines.pushback(line[m.end():])
                    return m.group(1)

        return get_subsection_name

    m = re.match(r"^[0-9]+\. ([a-z]+(\s+[a-z]+)*):", line, re.I)
    if m:
        def get_subsection_name(in_lines):
            in_lines.pushback(line[m.end():])
            return m.group(1)
        return get_subsection_name


top_section_matcher = make_matcher(r"^([^a-z]{2,}):$", group=1, fn=str.lower)


def generate_sections(lines, matchers):
    """
    :param lines: An iterable of strings
    :param matchers: An iterable of functions

    :returns: A generator that produces 2-tuples containing each section
    name and its contents as a list of strings

    """
    section_name = "header"
    section = []

    for line in lines:
        line = line.strip()
        new_section_name = None

        for matcher in matchers:
            name = matcher(line)

            if callable(name):
                name = name(lines)

            if isinstance(name, str):
                new_section_name = name
                break

        if new_section_name:
            if section:
                yield section_name, section
            section_name = new_section_name
            section = []
        else:
            section.append(line)

    yield section_name, section


def make_sections(lines, matchers):
    """Partition the contents of a file into sections using the given list
    of matchers.

    :param lines: An iterator or generator that produces lines of text
    input

    :param matchers: A list of callables that, when called with a line
    of text, should return either None, a section name, or a callable.

    :returns: An OrderedDict mapping section names to section contents
    (a list of string)

    """
    return OrderedDict(generate_sections(lines, matchers))


STRIP_LINES = "|".join([
    r"CITY HALL\s+93 HIGHLAND AVENUE\s+SOMERVILLE, MASSACHUSETTS 02143",
    r"\(617\) 625-6600 EXT\. 2500  TTY: \(617\) 666-0001  FAX: \(617\) 625-0722",
    r"^\s*www.somervillema.gov\s*$",
    r"^\s*Page \d+ of \d+\s*$",
])

STRIP_ADDITIONAL = "|".join([r"^Date: .* \d{4}$", r"^Case #:", r"^Site:"])


def filter_lines(lines, strip_lines=STRIP_LINES):
    """Returns a generator that filters out lines from the iterable that match
    any of the patterns in `strip_lines`."""
    patt = re.compile(strip_lines)
    return filter(lambda l: not patt.search(l), lines)


STAFF_REPORT_SECTION_MATCHERS = [
    make_matcher(r"(PLANNING|ZBA) STAFF REPORT", fn=str.lower),
    make_matcher(r"^[IVX]+\. ([^a-z]+)(\n|$)", group=1, fn=str.lower)
]


def staff_report_sections(lines):
    return make_sections(lines, STAFF_REPORT_SECTION_MATCHERS)



# Decision Documents
def find_vote(decision):
    """From the decision text, perform a very crude pattern match that extracts
    the vote (for/against).
    """
    patt = re.compile(r"voted (\d+-\d+) to (approve|deny)", re.I)
    m = re.search(patt, decision)

    return (m.group(1), m.group(2)) if m else (None, None)


DECISION_SECTION_MATCHERS = [
    skip_match(r"CITY HALL", 2),
    make_matcher(r"(ZBA DECISION|DESCRIPTION|PLANNING BOARD DECISION):?",
        value="properties"),
    make_matcher(r"DECISION:", value="decision"), top_section_matcher
]


def decision_sections(doc):
    return make_sections(filter_lines(doc.line_iterator),
                         DECISION_SECTION_MATCHERS)


def remove_match(s, m):
    return s[0:m.start()].rstrip() + s[m.end():]


ALL_EXTRACTORS = []

def extractor(*preds):
    def decorator_fn(process):
        def wrapped_fn(document):
            if all(pred(document) for pred in preds):
                return process(document)
            return {}

        wrapped_fn.__name__ = process.__name__
        wrapped_fn.__module__ = process.__module__
        ALL_EXTRACTORS.append(wrapped_fn)

        return wrapped_fn

    return decorator_fn


def region_matches(pattern):
    "Extractor predicate for matching the document's region name."
    return lambda doc: re.search(pattern, doc.region_name)


def field_matches(pattern):
    """Extractor predicate that matches against the field where the document link
    was found.

    """
    return lambda doc: re.search(pattern, doc.field)


def has_tags(tags):
    tagset = set([tags] if isinstance(tags, str) else tags)
    return lambda doc: tagset < doc.tag_set


def title_matches(pattern):
    "Extractor predicate that matches the document title."
    return lambda doc: re.search(pattern, doc.title)


SomervilleMA = region_matches(r"^Somerville, MA$")
CambridgeMA = region_matches(r"^Cambridge, MA$")

def somerville_properties(lines):
    props = properties(lines)
    app_owner_name = props.get("Applicant / Owner Name")
    app_owner_addr = props.get("Applicant / Owner Address")

    if app_owner_name:
        props["Applicant Name"] = app_owner_name
        props["Owner Name"] = app_owner_name
        del props["Applicant / Owner Name"]
    if app_owner_addr:
        props["Applicant Address"] = app_owner_addr
        props["Owner Address"] = app_owner_addr
        del props["Applicant / Owner Address"]
    return props


@extractor(SomervilleMA, field_matches(r"^reports$"),
           title_matches(r"(?i)staff[ _]?report"))
def staff_report_properties(doc):
    """Extract a dictionary of properties from the plaintext contents of a
    Planning Staff Report.
    """
    sections = staff_report_sections(filter_lines(doc.line_iterator, STRIP_LINES))
    attrs = {}
    props = {}

    attrs.update(somerville_properties(sections["header"]))
    for section in sections:
        if "staff report" in section:
            attrs.update(somerville_properties(sections[section]))

    try:
        if "Legal Notice" in attrs:
            props["summary"] = attrs["Legal Notice"]
    except AttributeError:
        pass

    if "Recommendation" in attrs:
        if re.match(r"^(?i)(conditional )?approval", attrs["Recommendation"]):
            props["status"] = "Recommend Approval"
        elif re.match(r"^(?i)denial", attrs["Recommendation"]):
            props["status"] = "Recommend Denial"

    desc_section = sections.get("project description")
    if desc_section:
        subsections = make_sections(
            pushback_iter(filter_lines(desc_section, STRIP_ADDITIONAL)),
            [subsection_matcher])

        for pname in [
                "Proposal", "Subject Property", "Green Building Practices"
        ]:
            v = subsections.get(pname)
            if v:
                attrs[pname] = "\n".join(paragraphize(v))

    return props, attrs


@extractor(SomervilleMA, field_matches("(?i)decision"))
def decision_properties(doc):
    """
    Extract a dictionary of properties from the contents of a Decision
    Document.
    """
    sections = decision_sections(doc)
    attrs = {}
    props = {}
    if "properties" in sections:
        attrs.update(somerville_properties(sections["properties"]))

    if "header" in sections:
        header_props = somerville_properties(sections["header"])
        copy_header_attrs = ["Decision", "Date of Decision", "Date Filed with City Clerk"]
        attrs.update(
            {k: header_props[k] for k in copy_header_attrs if k in header_props})

    if "Date" in attrs:
        del attrs["Date"]
    if "Site" in attrs:
        del attrs["Site"]

    if "Legal Notice" in header_props:
        attrs["Legal Notice"] = header_props["Legal Notice"]
        props["summary"] = header_props["Legal Notice"]

    vote, decision = find_vote(" ".join(sections["decision"]))
    if vote:
        concur, dissent, *_ = re.findall(r"\d+", vote)
        approved = bool(re.match(r"(?i)approve", decision))
        attrs["Vote"] = vote
        attrs["Votes to Approve"] = concur if approved else dissent
        attrs["Votes to Deny"] = dissent if approved else concur

        if "Decision" not in attrs:
            attrs["Decision"] = decision.title()
        props["status"] = "Approved" if approved else "Denied"

    try:
        props["complete"] = pytz.timezone("US/Eastern").localize(
            dt_parse(attrs["Date of Decision"])).isoformat()
    except (ValueError, KeyError):
        props["complete"] = doc.published.isoformat()

    return props, attrs

def get_properties(doc):
    """Runs all matching extractors on doc and merges the extracted properties.
    """
    all_props, all_attributes = {}, {}
    for extract in ALL_EXTRACTORS:
        extracted = extract(doc)
        if isinstance(extracted, tuple):
            all_props.update(extracted[0])
            all_attributes.update(extracted[1])
        else:
            all_attributes.update(extracted)

    all_props["attributes"] = all_attributes

    if "updated_date" not in all_props:
        all_props["updated_date"] = doc.published.isoformat()

    return all_props
