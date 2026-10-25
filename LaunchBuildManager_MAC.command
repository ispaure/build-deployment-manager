#!/bin/bash

PROJECT_ROOT="$(cd -- "$(dirname -- "$0")" && pwd)"
CONFIG_FILE="$PROJECT_ROOT/launch_config.ini"

if [[ ! -f "$CONFIG_FILE" ]]; then
    echo "ERROR: launch_config.ini was not found:"
    echo "  $CONFIG_FILE"
    exit 1
fi

read_config_value() {
    awk -F= -v key="$1" '
        $0 ~ "^[[:space:]]*" key "[[:space:]]*=" {
            value=$2
            sub(/^[[:space:]]*/, "", value)
            sub(/[[:space:]]*$/, "", value)
            print value
            exit
        }
    ' "$CONFIG_FILE"
}

COMMONUTILS_ROOT="$(read_config_value commonutils_root)"
PAUSE_AFTER_COMPLETED="$(read_config_value pause_after_completed)"
PAUSE_AFTER_COMPLETED="${PAUSE_AFTER_COMPLETED:-false}"

if [[ -z "$COMMONUTILS_ROOT" ]]; then
    echo "ERROR: commonutils_root was not found in launch_config.ini."
    exit 1
fi

LAUNCHER="$PROJECT_ROOT/$COMMONUTILS_ROOT/launchers/LaunchPythonProject_MAC.command"

if [[ ! -f "$LAUNCHER" ]]; then
    echo "Initialize the pinned dependency with: git submodule update --init --recursive"
    echo "ERROR: Shared Python launcher was not found:"
    echo "  $LAUNCHER"
    exit 1
fi

/bin/bash "$LAUNCHER" "$PROJECT_ROOT" "$CONFIG_FILE" "$PAUSE_AFTER_COMPLETED" "$@"
exit $?
