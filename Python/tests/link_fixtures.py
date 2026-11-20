# Copyright (c) 2026 ispaure
# SPDX-License-Identifier: MIT

"""Exercise native directory redirection without requiring Windows symlink privileges."""
import os
from commonUtils.filesystem.links import create_link


def directory_link(link, target):
    target.mkdir(parents=True, exist_ok=True)
    return create_link(target, link, 'junction' if os.name == 'nt' else 'symbolic')
