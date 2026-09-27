#!/bin/sh
# SPDX-License-Identifier: MIT
# Native tests of common/libs/cs_roles. test_ras needs no Zephyr headers; the
# others build against the real Zephyr and NCS Bluetooth headers.
# ZEPHYR_BASE: the NCS zephyr directory, e.g. /opt/nordic/ncs/v3.4.1-rc1/zephyr.
set -eu
cd "$(dirname "$0")/../.."
bin_dir=$(mktemp -d /tmp/cs_roles_test.XXXXXX)
trap 'rm -rf "$bin_dir"' EXIT
${CC:-cc} -std=c11 -Wall -Wextra -Werror -fsanitize=address,undefined \
    -Icommon/libs \
    common/libs/cs_roles/cs_ras.c tests/cs_roles/test_ras.c -o "$bin_dir/ras"
"$bin_dir/ras"

. tests/cs_roles/flags.sh
cs_utils="common/libs/cs_utils/cs_config.c common/libs/cs_utils/cs_capabilities.c
    common/libs/cs_utils/cs_reports.c common/libs/cs_utils/cs_results.c
    common/libs/cs_utils/cs_print.c"
# shellcheck disable=SC2086 # the flag and source lists are word lists
${CC:-cc} $cs_roles_flags -Itests/cs_roles \
    tests/cs_roles/test_role_sm.c tests/cs_roles/bt_stubs.c \
    common/libs/cs_roles/cs_role_initiator.c common/libs/cs_roles/cs_role_reflector.c \
    common/libs/cs_roles/cs_ras.c $cs_utils -o "$bin_dir/role_sm"
"$bin_dir/role_sm"
# shellcheck disable=SC2086
${CC:-cc} $cs_roles_flags -Itests/cs_roles \
    tests/cs_roles/test_events.c tests/cs_roles/bt_stubs.c $cs_utils -o "$bin_dir/events"
"$bin_dir/events"
# shellcheck disable=SC2086
${CC:-cc} $cs_roles_flags -Icommon/libs/cs_protocol -Itests/cs_roles \
    tests/cs_roles/test_stream.c tests/cs_roles/bt_stubs.c common/libs/cs_roles/cs_role_events.c \
    common/libs/host_link/host_link_reports.c common/libs/host_link/host_link_frame.c \
    common/libs/cs_protocol/cs_protocol.c $cs_utils -o "$bin_dir/stream"
"$bin_dir/stream"
