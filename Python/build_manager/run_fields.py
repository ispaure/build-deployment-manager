"""Project-declared, non-secret inputs captured for one reviewed run."""
import re
import json
from .credentials import reject_secrets


def validate_fields(fields, capabilities, journey=None):
    if not isinstance(fields, list):
        raise ValueError('Run fields must be a list.')
    seen=set()
    for row in fields:
        if (not isinstance(row, dict) or not isinstance(row.get('id'), str)
                or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*',row['id']) or row['id'] in seen
                or row.get('kind','text') not in {'text','multiline','multiselect'}
                or not isinstance(row.get('label'),str) or not row['label']):
            raise ValueError('Run fields need unique IDs, labels and supported input kinds.')
        for key in ('operations','destinations'):
            if not isinstance(row.get(key,[]),list) or any(not isinstance(v,str) for v in row.get(key,[])):
                raise ValueError('Run field applicability must be declared as lists of names.')
        if any(value not in capabilities['operations'] for value in row.get('operations',[])):
            raise ValueError('Run field has an unsupported operation.')
        if any(value not in (journey or {}).get('destinations',{}) for value in row.get('destinations',[])):
            raise ValueError('Run field has an unsupported destination.')
        seen.add(row['id'])
    reject_secrets(fields)
    for name, row in (journey or {}).get('destinations', {}).items():
        key = row.get('recipient_field')
        if key and not any(field['id'] == key and field.get('kind') == 'multiselect'
                           and name in field.get('destinations', []) for field in fields):
            raise ValueError('Delivery recipient fields must name a declared multiselect input.')


def validate_overrides(fields, values):
    if not isinstance(values,dict):
        raise ValueError('Run overrides must be a mapping.')
    allowed={row['id'] for row in fields}
    if set(values)-allowed or any(not isinstance(value,str) or len(value)>20000 for value in values.values()):
        raise ValueError('Only declared text inputs can be overridden for this run.')
    reject_secrets(values)
    for row in fields:
        if row.get('kind') == 'multiselect' and row['id'] in values:
            selection_ids(values[row['id']])
    return dict(values)


def selection_ids(value):
    try:
        rows = json.loads(value)
    except (ValueError, TypeError) as error:
        raise ValueError('Choose specific device IDs from the list or add a paired device ID.') from error
    if (not isinstance(rows, list) or len(rows) > 50 or any(not isinstance(key, str)
            or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}', key) for key in rows)
            or len(set(rows)) != len(rows)):
        raise ValueError('Choose up to 50 distinct device IDs using letters, numbers, dots, colons or hyphens.')
    return rows
