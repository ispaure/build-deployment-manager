"""Approval card data from a retained plan and its prerequisite results only."""
import json
from pathlib import PurePath

from .plan_summary import phase_title
from .workflows import ancestors


def approval_cards(plan, report, steps, fields=(), previews=None):
    phases = {phase.id: phase for phase in plan.phases}
    destinations = getattr(plan, 'journey', {}).get('destinations', {})
    values = {**plan.source.get('run_overrides', {}),
              **plan.source.get('effective_settings', {}).get('values', {})}
    cards = []
    for step in steps:
        phase = phases.get(step)
        targets = {name: row for name, row in destinations.items() if step in row['steps']}
        recipients, choices = [], []
        for field in fields:
            if field['id'] not in values:
                continue
            scope = set(field.get('destinations', ()))
            if scope and not scope.intersection(targets):
                continue
            value = values[field['id']]
            if field.get('kind') == 'multiselect':
                try:
                    selected = json.loads(value)
                    if not isinstance(selected, list) or not all(isinstance(v, str) for v in selected):
                        raise ValueError('Invalid captured selection')
                    value = ', '.join(selected) or 'None selected'
                except (ValueError, TypeError):
                    value = str(value)
                recipients.append((field['label'], value))
            elif field.get('kind') == 'choice':
                choices.append((field['label'], field.get('options', {}).get(value, value)))
        needed = ancestors(plan, step) if phase else set()
        builds = []
        seen = set()
        for row in report.get('phases', ()):
            if row['id'] not in needed:
                continue
            for artifact in row.get('artifacts', ()):
                identity = (artifact['path'], artifact['sha256'])
                if identity in seen:
                    continue
                seen.add(identity)
                # Optional scalar identity hints are presentation only. Approval
                # continues to bind the complete verified artifact, not these keys.
                preview = (previews or {}).get(artifact['path'], {})
                identity_fields = ('package', 'version', 'version_name', 'version_code',
                    'build', 'build_number', 'bundle_id', 'application_id')
                identity = [(key.replace('_', ' ').capitalize(), preview[key]) for key in identity_fields
                    if isinstance(preview, dict) and key in preview
                    and type(preview[key]) in (str, int, float)]
                builds.append(dict(name=PurePath(artifact.get('original_path') or artifact['path']).name,
                    sha256=artifact['sha256'], path=artifact['path'], kind=artifact.get('kind', 'file'),
                    identity=identity))
        cards.append(dict(step=step, title=phase_title(phase) if phase else step,
            destinations=[row['identity'] for row in targets.values()],
            platforms=list(dict.fromkeys(target for row in targets.values()
                for target in row.get('platforms', getattr(plan, 'journey', {}).get('platforms', {})))),
            recipients=recipients, choices=choices, builds=builds))
    return cards
