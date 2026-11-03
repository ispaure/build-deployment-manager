"""Editable device labels. Selecting recipients remains a checkout decision."""
import configparser
import json

from .credentials import reject_secrets
from .run_fields import parse_multiselect_ids


def recipient_platforms_by_field(descriptor):
    fields = {}
    for row in (descriptor.get('journey') or {}).get('destinations', {}).values():
        field = row.get('recipient_field')
        platforms = row.get('platforms', [])
        if field and len(platforms) == 1 and platforms[0] in ('ios', 'android'):
            fields.setdefault(field, set()).add(platforms[0])
    return {key: next(iter(platforms)) for key, platforms in fields.items() if len(platforms) == 1}


def read_device_labels(path):
    parser = configparser.ConfigParser(interpolation=None, delimiters=('=',), default_section='__defaults__')
    parser.optionxform = str
    try:
        parser.read_string(path.read_text(encoding='utf-8'))
        if parser.sections() != ['devices'] or parser.defaults():
            raise ValueError('Expected a single [devices] section.')
        labels = dict(parser['devices'])
        for key, label in labels.items():
            parse_multiselect_ids(json.dumps([key]))
            if not label.strip() or '\n' in label:
                raise ValueError('Each device needs a one-line label.')
        reject_secrets(labels)
        return labels
    except (ValueError, configparser.Error) as error:
        raise ValueError(f'Invalid device catalog {path}: {error}') from error


def merge_recipient_choices(directory, fields, rows):
    result = dict(rows)
    for field, platform in fields.items():
        path = directory / 'configuration' / 'devices' / (platform + '.ini')
        labels = read_device_labels(path)
        choices = result.get(field, [])
        # Keep adapter-specific metadata. The local catalog can relabel a device.
        merged = {}
        for row in choices:
            key = row['id']
            parse_multiselect_ids(json.dumps([key]))
            if key in merged or not isinstance(row.get('label'), str):
                raise ValueError('Invalid project device list.')
            label = labels.get(key, key)
            merged[key] = dict(row, label=row['label'] if label == key else label)
        for key, label in labels.items():
            merged.setdefault(key, dict(id=key, label=label))
        result[field] = list(merged.values())
    return result
