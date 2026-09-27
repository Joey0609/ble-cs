#!/bin/sh
# SPDX-License-Identifier: MIT
set -eu
cd "$(dirname "$0")/../.."
host_link_test_bin=$(mktemp /tmp/host_link_test.XXXXXX)
trap 'rm -f "$host_link_test_bin"' EXIT
${CC:-cc} -std=c11 -Wall -Wextra -Werror -fsanitize=address,undefined \
    -Itests/host_link/include -Icommon/libs -Icommon/libs/cs_protocol \
    common/libs/cs_protocol/cs_protocol.c \
    common/libs/host_link/host_link_config_store.c \
    tests/host_link/test_config_store.c -o "$host_link_test_bin"
"$host_link_test_bin"
${CC:-cc} -std=c11 -Wall -Wextra -Werror -fsanitize=address,undefined \
    -Itests/host_link/include -Icommon/libs -Icommon/libs/cs_protocol \
    common/libs/host_link/host_link_names.c \
    tests/host_link/test_names.c -o "$host_link_test_bin"
"$host_link_test_bin"
${CC:-cc} -std=c11 -Wall -Wextra -Werror -fsanitize=address,undefined \
    -Itests/host_link/include -Icommon/libs -Icommon/libs/cs_protocol \
    common/libs/cs_protocol/cs_protocol.c tests/host_link/test_peer_packets.c \
    -o "$host_link_test_bin"
"$host_link_test_bin"
${CC:-cc} -std=c11 -Wall -Wextra -Werror -fsanitize=address,undefined \
    -Itests/host_link/include -Icommon/libs -Icommon/libs/cs_protocol \
    tests/host_link/test_config_antennas.c -o "$host_link_test_bin"
"$host_link_test_bin"
${CC:-cc} -std=c11 -Wall -Wextra -Werror -fsanitize=address,undefined \
    -Itests/host_link/include -Icommon/libs -Icommon/libs/cs_protocol \
    common/libs/cs_protocol/cs_protocol.c common/libs/host_link/host_link_frame.c \
    tests/host_link/test_frame_writer.c -o "$host_link_test_bin"
"$host_link_test_bin"
# host_link.c itself, with the transport, app_log and the application stubbed
# in the test; the CONFIG_ values are the Kconfig defaults.
${CC:-cc} -std=c11 -Wall -Wextra -Werror -fsanitize=address,undefined \
    -Itests/host_link/include -Icommon/libs -Icommon/libs/cs_protocol \
    -DCONFIG_APP_HOST_LINK_MAX_FRAME_SIZE=512 -DCONFIG_APP_LOG_MESSAGE_MAX=256 \
    -DCONFIG_APP_HOST_LINK_THREAD_STACK_SIZE=2048 -DCONFIG_APP_HOST_LINK_THREAD_PRIORITY=10 \
    -DCONFIG_APP_HOST_LINK_DTR_POLL_MS=100 -DCONFIG_APP_HOST_LINK_REPORT_TIMEOUT_MS=100 \
    -DCONFIG_APP_HOST_LINK_NUM_ANTENNAS=4 -DCONFIG_APP_HOST_LINK_DTR=1 \
    common/libs/cs_protocol/cs_protocol.c common/libs/host_link/host_link_config_store.c \
    common/libs/host_link/host_link_names.c tests/host_link/test_commands.c \
    -o "$host_link_test_bin"
"$host_link_test_bin"
