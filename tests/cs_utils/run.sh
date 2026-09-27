#!/bin/sh
# SPDX-License-Identifier: MIT
# Native tests of common/libs/cs_utils against the real Zephyr Bluetooth headers.
# ZEPHYR_BASE: the NCS zephyr directory, e.g. /opt/nordic/ncs/v3.4.1-rc1/zephyr.
set -eu
cd "$(dirname "$0")/../.."
: "${ZEPHYR_BASE:?set ZEPHYR_BASE to the NCS zephyr directory}"
bin_dir=$(mktemp -d /tmp/cs_utils_test.XXXXXX)
trap 'rm -rf "$bin_dir"' EXIT
# The kernel stub comes first; CONFIG_ARCH_POSIX and the builtin atomics let the
# Zephyr toolchain and atomic headers build for the host.
${CC:-cc} -std=gnu11 -Wall -Wextra -Werror -fsanitize=address,undefined \
    -DCONFIG_ARCH_POSIX -DCONFIG_ATOMIC_OPERATIONS_BUILTIN \
    -Itests/cs_utils/include -Icommon/libs -I"$ZEPHYR_BASE/include" \
    common/libs/cs_utils/cs_config.c common/libs/cs_utils/cs_print.c \
    tests/cs_utils/test_config.c -o "$bin_dir/config"
"$bin_dir/config"
