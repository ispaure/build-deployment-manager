# Copyright (c) 2026 ispaure
# SPDX-License-Identifier: MIT

"""Select project-required gates and recorded artifacts from a saved run."""
from pathlib import Path


def passed_phase_rows(report, phase_ids):
    """Require exactly one successful result for every selected phase."""
    selected = {}
    required = set(phase_ids)
    for row in report['phases']:
        phase = row['id']
        if phase not in required:
            continue
        if phase in selected or row.get('status') != 'passed':
            raise ValueError('Required saved phase is ambiguous or did not pass: ' + phase)
        selected[phase] = row
    if required - selected.keys():
        raise ValueError('Required saved phases are missing: ' + ', '.join(sorted(required - selected.keys())))
    return selected


def select_artifact(row, original_path, *, copied_under=None):
    """Find the receipt for a declared output, optionally requiring a retained copy."""
    original = Path(original_path)
    matches = [artifact for artifact in row.get('artifacts', ())
               if artifact.get('original_path', artifact.get('path')) == str(original)]
    if len(matches) != 1 or not isinstance(matches[0].get('path'), str):
        raise ValueError('Saved phase lacks an exact, unique artifact receipt: ' + str(original))
    receipt = matches[0]
    if copied_under is not None:
        path = Path(receipt['path'])
        if path == original or path.parent != Path(copied_under) or not path.is_absolute() or path.resolve() != path:
            raise ValueError('The saved artifact is not a canonical retained copy: ' + str(path))
    return receipt


def verify_artifact(receipt, digest, *, verify_original=True):
    """Check the recorded bytes, with optional verification of the original output."""
    path = Path(receipt['path'])
    original = Path(receipt.get('original_path', receipt['path']))
    expected = receipt['sha256']
    if (not path.is_file() or digest(path) != expected
            or verify_original and original != path and (
                not original.is_file() or digest(original) != expected)):
        raise ValueError('Retained artifact is missing or changed; inspect a new preparation: ' + str(path))
