"""Bounded, dependency-free ingestion of explicitly declared JUnit evidence."""
import math
from pathlib import Path
import re
import xml.etree.ElementTree as ET

MAX_REPORT_BYTES = 8 * 1024 * 1024
MAX_CASES = 20000
STAGE_LABELS = {'smoke': 'Smoke', 'regression': 'Regression', 'extended': 'Extended'}

TIERS = {'unit', 'contracts', 'integration', 'ui', 'native', 'acceptance'}


def stage_label(case):
    return STAGE_LABELS.get(case.get('stage'), 'Unspecified')


def validate_suites(suites, capabilities):
    if not isinstance(suites, list):
        raise ValueError('test_suites must be a list.')
    seen = set()
    for suite in suites:
        if not isinstance(suite, dict):
            raise ValueError('Each test suite must be an object.')
        key = suite.get('id')
        if not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', key) or key in seen:
            raise ValueError('Test suite IDs must be stable and unique.')
        seen.add(key)
        if (not isinstance(suite.get('label'), str) or not suite['label'].strip()
                or not isinstance(suite.get('tier'), str) or suite['tier'] not in TIERS):
            raise ValueError('Test suites need a label and a supported tier.')
        if not isinstance(suite.get('description', ''), str):
            raise ValueError('Test suite description must be text.')
        for field in ('platforms', 'operations'):
            choices = suite.get(field)
            if (not isinstance(choices, list) or not choices
                    or any(value not in capabilities[field] for value in choices)):
                raise ValueError('Test suite must declare supported ' + field + '.')
    return suites


def read_junit(path):
    """Return case facts only; no console guessing or execution of report content."""
    with Path(path).open('rb') as stream:
        raw = stream.read(MAX_REPORT_BYTES + 1)
    if len(raw) > MAX_REPORT_BYTES:
        raise ValueError('JUnit report exceeds the 8 MiB limit.')
    # Restrict to UTF-8 so encoded DTD declarations cannot bypass this check.
    try:
        text = raw.decode('utf-8-sig')
    except UnicodeError as error:
        raise ValueError('JUnit report must use UTF-8.') from error
    if re.search(r'<!\s*(DOCTYPE|ENTITY)', text, re.I):
        raise ValueError('JUnit reports cannot declare DTDs or entities.')
    try:
        root = ET.fromstring(text)
    except ET.ParseError as error:
        raise ValueError('Invalid JUnit XML: ' + str(error)) from error
    def tag(element):
        return element.tag.rsplit('}', 1)[-1]
    if tag(root) not in {'testsuite', 'testsuites'}:
        raise ValueError('JUnit root must be testsuite or testsuites.')
    cases = []
    def walk(element, suite=''):
        if tag(element) == 'testsuite':
            suite = element.get('name', suite)
        if tag(element) == 'testcase':
            if len(cases) >= MAX_CASES:
                raise ValueError('JUnit report exceeds the case limit.')
            name = element.get('name', '')
            if not name:
                raise ValueError('JUnit testcase needs a name.')
            try:
                seconds = float(element.get('time')) if element.get('time') is not None else None
            except ValueError as error:
                raise ValueError('JUnit case time must be seconds.') from error
            if seconds is not None and (not math.isfinite(seconds) or seconds < 0):
                raise ValueError('JUnit case time must be finite and nonnegative.')
            outcomes = {tag(child): child for child in element}
            status = next((value for value in ('error', 'failure', 'skipped') if value in outcomes), 'passed')
            detail = outcomes.get(status)
            message = '' if detail is None else (detail.get('message', '') + '\n' + ''.join(detail.itertext())).strip()
            stages = [prop.get('value') for child in element if tag(child) == 'properties'
                      for prop in child if tag(prop) == 'property' and prop.get('name') == 'test_stage']
            if len(stages) > 1 or stages and stages[0] not in STAGE_LABELS:
                raise ValueError('JUnit test_stage must be smoke, regression or extended, declared once.')
            cases.append(dict(name=name, classname=element.get('classname', ''), suite=suite,
                              status='failed' if status == 'failure' else status, seconds=seconds,
                              message=message[:16000], **({'stage': stages[0]} if stages else {})))
        for child in element:
            walk(child, suite)
    try:
        walk(root)
    except RecursionError as error:
        raise ValueError('JUnit report is nested too deeply.') from error
    if not cases:
        raise ValueError('JUnit report contains no test cases.')
    return cases
