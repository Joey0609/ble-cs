# SPDX-License-Identifier: MIT

cmake_minimum_required(VERSION 3.20.0)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

# Avoid archive failures with the NCS toolchain's ccache link launcher.
set(USE_CCACHE 0)

find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})
project(radio_test)

# The radio test driver is used as-is from the NCS sample. Only its shell
# front-end (radio_cmd.c) is left out; the test configuration lives in
# src/radio_test_cfg.c instead.
set(NCS_RADIO_TEST_DIR ${ZEPHYR_NRF_MODULE_DIR}/samples/peripheral/radio_test/src)

set(APP_LIBS_RADIO_TEST ON)
include(${CMAKE_CURRENT_SOURCE_DIR}/../../common/libs/libs.cmake)
target_link_libraries(app PRIVATE app_libs)

target_sources(app PRIVATE
    ${NCS_RADIO_TEST_DIR}/radio_test.c
    src/main.c
    src/radio_test_cfg.c
)

target_include_directories(app PRIVATE ${NCS_RADIO_TEST_DIR})

# Keep the compilation database where clangd discovers it automatically.
add_custom_target(copy_compile_commands ALL
        COMMAND ${CMAKE_COMMAND} -E copy_if_different
                ${CMAKE_BINARY_DIR}/compile_commands.json
                ${CMAKE_CURRENT_SOURCE_DIR}/compile_commands.json
        DEPENDS zephyr_final
        COMMENT "Copying compile_commands.json for clangd"
)
