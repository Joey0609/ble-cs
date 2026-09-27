#!/bin/sh
# SPDX-License-Identifier: MIT
set -eu
cd "$(dirname "$0")/../.."
bin_dir=$(mktemp -d /tmp/cs_generated_config_test.XXXXXX)
trap 'rm -rf "$bin_dir"' EXIT
build() {
    ${CC:-cc} -std=c11 -Wall -Wextra -Werror -fsanitize=address,undefined \
        -Itests/cs_generated_config/include -Icommon/libs -Itests/cs_generated_config \
        common/libs/cs_generated_config/cs_generated_config.c \
        tests/cs_generated_config/stub_cs_config.c \
        tests/cs_generated_config/test_generated_config.c "$@"
}
build -o "$bin_dir/weak"
build -DTEST_WITH_GENERATED tests/cs_generated_config/generated_fixture.c -o "$bin_dir/generated"
"$bin_dir/weak"
"$bin_dir/generated"
