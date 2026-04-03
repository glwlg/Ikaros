#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." >/dev/null 2>&1 && pwd)"
IKAROS_HOME="${IKAROS_HOME:-${HOME}/.ikaros}"
IKAROS_DATA_DIR="${IKAROS_HOME}/data"
LOG_DIR="${IKAROS_DATA_DIR}/logs"
RUN_DIR="${IKAROS_DATA_DIR}/run"
API_PORT="8764"

usage() {
    cat <<'EOF'
Usage:
  scripts/restart_services.sh [all|ikaros|api|status]

Description:
  Restart ikaros and/or ikaros-api.
  Detection order:
    1. shell_bg if a live pid file exists
    2. systemd user/system service if an installed unit exists
    3. launchd agent if an installed plist exists
    4. fallback to shell_bg
EOF
}

info() {
    printf '[INFO] %s\n' "$*"
}

fail() {
    printf '[ERROR] %s\n' "$*" >&2
    exit 1
}

os_kind() {
    local uname_s
    uname_s="$(uname -s 2>/dev/null || echo unknown)"
    case "${uname_s}" in
        Linux) printf 'linux\n' ;;
        Darwin) printf 'macos\n' ;;
        *) printf 'other\n' ;;
    esac
}

display_name() {
    case "${1:-}" in
        api) printf 'ikaros-api\n' ;;
        *) printf 'ikaros\n' ;;
    esac
}

unit_name() {
    case "${1:-}" in
        api) printf 'ikaros-api\n' ;;
        *) printf 'ikaros\n' ;;
    esac
}

launchd_label() {
    case "${1:-}" in
        api) printf 'com.ikaros.api\n' ;;
        *) printf 'com.ikaros.core\n' ;;
    esac
}

runner_path() {
    case "${1:-}" in
        api) printf '%s\n' "${SCRIPT_DIR}/run_api.sh" ;;
        *) printf '%s\n' "${SCRIPT_DIR}/run_ikaros.sh" ;;
    esac
}

pid_file() {
    case "${1:-}" in
        api) printf '%s\n' "${RUN_DIR}/ikaros-api.pid" ;;
        *) printf '%s\n' "${RUN_DIR}/ikaros.pid" ;;
    esac
}

log_file() {
    case "${1:-}" in
        api) printf '%s\n' "${LOG_DIR}/ikaros-api.out.log" ;;
        *) printf '%s\n' "${LOG_DIR}/ikaros.out.log" ;;
    esac
}

launchd_plist() {
    printf '%s\n' "${HOME}/Library/LaunchAgents/$(launchd_label "${1:-}").plist"
}

launchd_is_loaded() {
    local label="$1"
    local domain="$2"

    if launchctl print "${domain}/${label}" >/dev/null 2>&1; then
        return 0
    fi

    launchctl list 2>/dev/null | awk '{print $3}' | grep -Fxq "${label}"
}

user_unit_path() {
    printf '%s\n' "${HOME}/.config/systemd/user/$(unit_name "${1:-}").service"
}

system_unit_path() {
    printf '%s\n' "/etc/systemd/system/$(unit_name "${1:-}").service"
}

read_pid() {
    local target="$1"
    if [[ ! -f "${target}" ]]; then
        return 1
    fi
    cat "${target}" 2>/dev/null || true
}

pid_is_alive() {
    local pid="$1"
    [[ -n "${pid}" && "${pid}" =~ ^[0-9]+$ ]] || return 1
    kill -0 "${pid}" >/dev/null 2>&1
}

shell_bg_running() {
    local service="$1"
    local target_pid_file pid
    target_pid_file="$(pid_file "${service}")"
    pid="$(read_pid "${target_pid_file}" || true)"
    pid_is_alive "${pid}"
}

detect_mode() {
    local service="$1"
    if shell_bg_running "${service}"; then
        printf 'shell_bg\n'
        return 0
    fi

    if command -v systemctl >/dev/null 2>&1; then
        if [[ -f "$(user_unit_path "${service}")" ]]; then
            printf 'systemd_user\n'
            return 0
        fi
        if [[ -f "$(system_unit_path "${service}")" ]]; then
            printf 'systemd_system\n'
            return 0
        fi
        if [[ -L "/etc/systemd/system/multi-user.target.wants/$(unit_name "${service}").service" ]]; then
            printf 'systemd_system\n'
            return 0
        fi
    fi

    if [[ "$(os_kind)" == "macos" ]] && [[ -f "$(launchd_plist "${service}")" ]]; then
        printf 'launchd\n'
        return 0
    fi

    printf 'shell_bg\n'
}

stop_shell_bg() {
    local service="$1"
    local target_pid_file pid
    target_pid_file="$(pid_file "${service}")"
    pid="$(read_pid "${target_pid_file}" || true)"

    if ! pid_is_alive "${pid}"; then
        rm -f "${target_pid_file}"
        return 0
    fi

    kill "${pid}" >/dev/null 2>&1 || true
    for _ in $(seq 1 20); do
        if ! pid_is_alive "${pid}"; then
            rm -f "${target_pid_file}"
            return 0
        fi
        sleep 0.5
    done

    fail "Failed to stop $(display_name "${service}") gracefully (PID ${pid})."
}

start_shell_bg() {
    local service="$1"
    local runner target_pid_file target_log_file
    runner="$(runner_path "${service}")"
    target_pid_file="$(pid_file "${service}")"
    target_log_file="$(log_file "${service}")"

    mkdir -p "${LOG_DIR}" "${RUN_DIR}"
    if [[ ! -x "${runner}" ]]; then
        chmod +x "${runner}"
    fi

    (
        cd "${PROJECT_DIR}"
        if [[ "${service}" == "api" ]]; then
            nohup "${runner}" --host 0.0.0.0 --port "${API_PORT}" >"${target_log_file}" 2>&1 &
        else
            nohup "${runner}" >"${target_log_file}" 2>&1 &
        fi
        echo $! >"${target_pid_file}"
    )

    info "Started $(display_name "${service}") in background (PID $(cat "${target_pid_file}")). Log: ${target_log_file}"
}

restart_systemd_user() {
    systemctl --user restart "$(unit_name "${1:-}")"
}

restart_systemd_system() {
    local unit
    unit="$(unit_name "${1:-}")"
    if [[ "${EUID}" -eq 0 ]]; then
        systemctl restart "${unit}"
        return 0
    fi

    if command -v sudo >/dev/null 2>&1; then
        sudo -n systemctl restart "${unit}" || fail "systemd system service restart requires root or passwordless sudo: ${unit}"
        return 0
    fi

    fail "systemd system service restart requires root: ${unit}"
}

restart_launchd() {
    local service="$1"
    local label plist domain
    label="$(launchd_label "${service}")"
    plist="$(launchd_plist "${service}")"
    domain="gui/$(id -u)"

    [[ -f "${plist}" ]] || fail "LaunchAgent plist not found: ${plist}"

    if launchd_is_loaded "${label}" "${domain}" && launchctl kickstart -k "${domain}/${label}" >/dev/null 2>&1; then
        return 0
    fi

    launchctl bootout "${domain}" "${plist}" >/dev/null 2>&1 || true
    if launchctl bootstrap "${domain}" "${plist}" >/dev/null 2>&1; then
        launchctl kickstart -k "${domain}/${label}" >/dev/null 2>&1 || true
        return 0
    fi

    launchctl unload "${plist}" >/dev/null 2>&1 || true
    launchctl load "${plist}"
}

restart_one() {
    local service="$1"
    local mode
    mode="$(detect_mode "${service}")"
    info "Restarting $(display_name "${service}") via ${mode}"
    case "${mode}" in
        shell_bg)
            stop_shell_bg "${service}"
            start_shell_bg "${service}"
            ;;
        systemd_user)
            restart_systemd_user "${service}"
            ;;
        systemd_system)
            restart_systemd_system "${service}"
            ;;
        launchd)
            restart_launchd "${service}"
            ;;
        *)
            fail "Unsupported restart mode for $(display_name "${service}"): ${mode}"
            ;;
    esac
}

status_one() {
    local service="$1"
    local mode state pid target_pid_file unit label domain restart_hint
    mode="$(detect_mode "${service}")"
    case "${mode}" in
        shell_bg)
            target_pid_file="$(pid_file "${service}")"
            pid="$(read_pid "${target_pid_file}" || true)"
            state="stopped"
            if pid_is_alive "${pid}"; then
                state="running"
            fi
            printf '%s: mode=%s state=%s pid=%s pid_file=%s\n' \
                "$(display_name "${service}")" "${mode}" "${state}" "${pid:-}" "${target_pid_file}"
            ;;
        systemd_user)
            unit="$(unit_name "${service}")"
            state="inactive"
            if systemctl --user is-active --quiet "${unit}" >/dev/null 2>&1; then
                state="active"
            fi
            printf '%s: mode=%s state=%s unit=%s\n' \
                "$(display_name "${service}")" "${mode}" "${state}" "${unit}"
            ;;
        systemd_system)
            unit="$(unit_name "${service}")"
            state="unknown"
            restart_hint="needs_root_or_passwordless_sudo"
            if [[ "${EUID}" -eq 0 ]]; then
                restart_hint="root"
            elif command -v sudo >/dev/null 2>&1 && sudo -n true >/dev/null 2>&1; then
                restart_hint="passwordless_sudo"
            fi
            if systemctl is-active --quiet "${unit}" >/dev/null 2>&1; then
                state="active"
            elif systemctl status "${unit}" >/dev/null 2>&1; then
                state="inactive"
            fi
            printf '%s: mode=%s state=%s unit=%s restart=%s\n' \
                "$(display_name "${service}")" "${mode}" "${state}" "${unit}" "${restart_hint}"
            ;;
        launchd)
            label="$(launchd_label "${service}")"
            domain="gui/$(id -u)"
            state="not_loaded"
            if launchd_is_loaded "${label}" "${domain}"; then
                state="loaded"
            fi
            printf '%s: mode=%s state=%s label=%s\n' \
                "$(display_name "${service}")" "${mode}" "${state}" "${label}"
            ;;
        *)
            fail "Unsupported status mode for $(display_name "${service}"): ${mode}"
            ;;
    esac
}

main() {
    local action="${1:-all}"
    case "${action}" in
        -h|--help|help)
            usage
            ;;
        status)
            status_one "ikaros"
            status_one "api"
            ;;
        all|"")
            restart_one "api"
            restart_one "ikaros"
            ;;
        ikaros|core)
            restart_one "ikaros"
            ;;
        api|ikaros-api)
            restart_one "api"
            ;;
        *)
            usage >&2
            fail "Unknown target: ${action}"
            ;;
    esac
}

main "$@"
