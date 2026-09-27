#!/bin/sh
# SPDX-License-Identifier: MIT
# Native tests of common/libs/app_log with a test-only kernel subset (include/).
set -eu
cd "$(dirname "$0")/../.."
app_log_test_bin=$(mktemp /tmp/app_log_test.XXXXXX)
trap 'rm -f "$app_log_test_bin"' EXIT
${CC:-cc} -std=c11 -Wall -Wextra -Werror -fsanitize=address,undefined \
    -DCONFIG_APP_LOG_MESSAGE_MAX=64 -DCONFIG_APP_LOG_QUEUE_DEPTH=4 \
    -DCONFIG_APP_LOG_THREAD_STACK_SIZE=1024 -DCONFIG_APP_LOG_THREAD_PRIORITY=12 \
    -Itests/app_log/include -Icommon/libs -Icommon/libs/app_log \
    common/libs/app_log/app_log.c common/libs/app_log/app_log_console.c \
    tests/app_log/test_app_log.c -o "$app_log_test_bin"
"$app_log_test_bin"
