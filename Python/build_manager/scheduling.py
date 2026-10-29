"""Pure scheduling decisions; execution, approvals and resource admission stay separate."""


def phase_is_ready(phase, *, running, pending, rows, max_workers, retry_after, now, cancelled):
    """Readiness requires completion edges; success gates are checked on admission."""
    if phase.reuse_key and any(active.reuse_key == phase.reuse_key for active in running):
        # Do not occupy workers waiting for an equivalent evidence producer.
        return False
    if not cancelled and now < retry_after.get(phase.id, 0):
        return False
    prerequisites = (*phase.dependencies, *phase.waits_for)
    if any(name not in rows or rows[name]['status'] in {'running', 'retrying'} for name in prerequisites):
        return False
    whole_workflow_cleanup = phase.always and not prerequisites
    if whole_workflow_cleanup:
        if running:
            return False
        if max_workers > 1 and any(not candidate.always for candidate in pending):
            return False
    return True


def skip_reason(phase, rows, *, cancelled):
    if phase.always:
        return ''
    if cancelled:
        return 'cancelled'
    if any(rows[name]['status'] != 'passed' for name in phase.dependencies):
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
