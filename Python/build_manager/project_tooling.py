"""Optional project-owned bootstrap results; installation policy stays in projects."""


def validate_status(value):
    if (not isinstance(value, dict) or type(value.get('ready')) is not bool
            or value.get('status') not in {'ready', 'needs_update', 'blocked'}
            or value['ready'] != (value['status'] == 'ready')
            or not isinstance(value.get('message'), str)
            or not isinstance(value.get('declared_revision'), str)
            or not isinstance(value.get('environments'), list)):
        raise ValueError('Project tooling must report readiness, declared revision and environment diagnostics.')
    names = set()
    for row in value['environments']:
        if (not isinstance(row, dict) or type(row.get('ready')) is not bool
                or any(not isinstance(row.get(key), str) for key in
                       ('name', 'interpreter', 'installed_revision', 'source_checkout'))
                or not row['name'] or not row['interpreter'] or row['name'] in names):
            raise ValueError('Project tooling environments need unique names, interpreters and installed provenance.')
        names.add(row['name'])
    if value['ready'] and (not names or any(not row['ready'] for row in value['environments'])):
        raise ValueError('Project tooling cannot be ready while an environment is unavailable.')
    return value
