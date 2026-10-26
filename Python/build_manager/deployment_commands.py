"""Interactive local commands; project policy supplies arguments and order.

Unlike execution plans, these compatibility commands inherit terminal input.
They do not certify tests, declare release acceptance or retry external effects.
"""
from dataclasses import dataclass
import json
from pathlib import Path
import subprocess


@dataclass(frozen=True)
class Command:
    argv: tuple[str, ...]
    cwd: str
    environment: dict[str, str] | None = None


@dataclass(frozen=True)
class CommandStep:
    label: str
    command: Command


def run_sequence(steps, *, starting=lambda step: None, continue_after_failure=lambda step, code: False):
    """Run in order with inherited input; a failure remains failed after continuing."""
    failed = []
    for step in steps:
        starting(step)
        command = step.command
        result = subprocess.run(list(command.argv), cwd=Path(command.cwd), env=command.environment)
        if result.returncode:
            failed.append(step)
            if not continue_after_failure(step, result.returncode):
                break
    return tuple(failed)


def confirmation_input(prompt, *, marker):
    """Emit the caller's existing newline-delimited protocol, then await its answer."""
    print('\n' + marker + json.dumps(prompt), flush=True)
    return input()
