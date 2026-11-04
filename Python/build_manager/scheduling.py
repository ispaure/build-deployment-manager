"""Pure scheduling decisions; execution, approvals and resource admission stay separate."""


def can_consider_phase(phase, *, running, pending, rows, max_workers, retry_not_before_by_phase, now, cancelled, deferred=()):
    """Readiness requires completion edges; success gates are checked on admission."""
    if phase.reuse_key and any(active.reuse_key == phase.reuse_key for active in running):
        # Do not occupy workers waiting for an equivalent evidence producer.
        return False
    if not cancelled and now < retry_not_before_by_phase.get(phase.id, 0):
        return False
    prerequisites = (*phase.dependencies, *phase.waits_for)
    if any(name not in deferred and (name not in rows or rows[name]['status'] in {'running', 'retrying'})
           for name in prerequisites):
        return False
    whole_workflow_cleanup = phase.always and not prerequisites
    if whole_workflow_cleanup:
        if running:
            return False
        if max_workers > 1 and any(not candidate.always for candidate in pending):
            return False
    return True


def defer_for_review(phase, rows, *, deferred, cancelled):
    """An approval pause is not a failed attempt of its unstarted consumers."""
    if phase.always or cancelled:
        return False
    if any(name not in deferred and rows[name]['status'] not in {'passed', 'awaiting_review'}
           for name in phase.dependencies):
        return False  # A genuine failed gate must still produce a retained skip.
    return any(name in deferred or rows[name]['status'] == 'awaiting_review'
               for name in (*phase.dependencies, *phase.waits_for))


def skip_reason(phase, rows, *, cancelled):
    if phase.always:
        return ''
    if cancelled:
        return 'cancelled'
    if any(rows.get(name, {}).get('status') != 'passed' for name in phase.dependencies):
        return 'dependency did not pass'
    return ''


def final_status(plan, rows, *, cancelled):
    statuses = [rows[phase.id]['status'] for phase in plan.phases
                if phase.id in rows and rows[phase.id]['required']]
    cleanup_failed = any(phase.always and phase.required and phase.id in rows
                         and rows[phase.id]['status'] != 'passed' for phase in plan.phases)
    if 'unknown' in statuses:
        return 'unknown'
    if cleanup_failed:
        return 'failed'
    if 'awaiting_review' in statuses:
        return 'awaiting_review'
    if cancelled:
        return 'cancelled'
    return 'failed' if any(status != 'passed' for status in statuses) else 'passed'
