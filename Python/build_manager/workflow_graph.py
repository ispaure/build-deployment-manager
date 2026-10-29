"""Pure display-graph calculations; executable dependencies remain unchanged."""

def layout_positions(phases):
    """Keep each column near its parents, preserving stable sibling order."""
    levels, rows = {}, {}
    visible = {phase.id for phase in phases}
    for phase in phases:
        parents = [key for key in (*phase.dependencies, *getattr(phase, 'waits_for', ())) if key in visible]
        level = 1 + max((levels[key] for key in parents), default=-1)
        levels[phase.id] = level
        rows.setdefault(level, []).append(phase)
    width = max((len(row) for row in rows.values()), default=1)
    positions = {}
    for level, row in rows.items():
        def parent_center(phase):
            parents = [key for key in (*phase.dependencies, *getattr(phase, 'waits_for', ())) if key in visible]
            nearest = max((levels[key] for key in parents), default=-1)
            parents = [key for key in parents if levels[key] == nearest]
            return sum(positions[key][1] for key in parents) / len(parents) if parents else width - 1
        ordered = sorted(row, key=parent_center)
        start = round(sum(parent_center(phase) for phase in ordered) / len(ordered) - len(ordered) + 1)
        for index, phase in enumerate(ordered):
            positions[phase.id] = (level, start + 2 * index)
    offset = min((lane for _, lane in positions.values()), default=0)
    return {key: (level, lane - min(0, offset)) for key, (level, lane) in positions.items()}


def visible_dependencies(phases):
    """Omit success arrows already implied by a visible success-only path.

    Completion waits and always-run steps do not propagate success, so they
    must never be used to hide a success requirement. Always-run targets only
    require completion, so their incoming arrows can use completion paths.
    Reduce only the drawing;
    the original plan remains the source for scheduling and inspection.
    """
    phases = {phase.id: phase for phase in phases}
    ancestors, completed_ancestors = {}, {}
    for key in phases:
        seen, pending = set(), [key]
        while pending:
            phase = phases[pending.pop()]
            if phase.always:
                continue
            for parent in phase.dependencies:
                if parent in phases and parent not in seen:
                    seen.add(parent)
                    pending.append(parent)
        ancestors[key] = seen
        seen, pending = set(), [key]
        while pending:
            phase = phases[pending.pop()]
            for parent in (*phase.dependencies, *getattr(phase, 'waits_for', ())):
                if parent in phases and parent not in seen:
                    seen.add(parent)
                    pending.append(parent)
        completed_ancestors[key] = seen
    edges = []
    for phase in phases.values():
        parents = [key for key in phase.dependencies if key in phases]
        implied = completed_ancestors if phase.always else ancestors
        alternatives = parents + ([key for key in getattr(phase, 'waits_for', ()) if key in phases]
                                  if phase.always else [])
        for parent in parents:
            if not any(parent in implied[other] for other in alternatives if other != parent):
                edges.append((parent, phase.id))
        edges.extend((key, phase.id) for key in getattr(phase, 'waits_for', ()) if key in phases)
    return edges


def connection_groups(edges, positions, order_edges=(), states=None, completion_targets=()):
    """Bundle only identical prerequisites with matching meaning and line style.

    Expanding each group's sources × targets reconstructs exactly the drawn
    graph. Long connections stay separate from adjacent-column junctions.
    """
    incoming = {}
    for source, target in edges:
        style = 'completion' if (source, target) in order_edges else (
            'blocked' if (states or {}).get(target, ('', ''))[0] in {'blocked', 'skipped'} else 'success')
        incoming.setdefault((target, positions[source][0], style), []).append(source)
    groups = {}
    for (target, level, style), sources in incoming.items():
        sources = tuple(sorted(set(sources)))
        adjacent = positions[target][0] == level + 1
        signature = (sources, positions[target][0], style, target in completion_targets,
                     None if adjacent else target)
        groups.setdefault(signature, []).append(target)
    return [(sources, tuple(targets), style)
            for (sources, _, style, _, _), targets in groups.items()]

