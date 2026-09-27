# SPDX-License-Identifier: MIT

cmake_minimum_required(VERSION 3.20.0)

# Shared radio-test and host-link settings apply to both UART variants.
list(APPEND EXTRA_CONF_FILE radio_test.conf common.conf)

find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})
project(cs_radio_test_client)

# This image uses direct RADIO/TIMER access through the NCS radio_test driver.
set(APP_LIBS_RADIO_TEST ON)
include(${CMAKE_CURRENT_SOURCE_DIR}/../common/libs/libs.cmake)
target_link_libraries(app PRIVATE app_libs)

set(NCS_RADIO_TEST_DIR ${ZEPHYR_NRF_MODULE_DIR}/samples/peripheral/radio_test/src)
target_sources(app PRIVATE
    ${NCS_RADIO_TEST_DIR}/radio_test.c
    ../cs_client/src/client_state.c
    ../cs_client/src/radio_session.c
    src/main.c
)
target_include_directories(app PRIVATE ../cs_client/src ${NCS_RADIO_TEST_DIR})


# Keep the compilation database where clangd discovers it automatically.
add_custom_target(copy_compile_commands ALL
        COMMAND ${CMAKE_COMMAND} -E copy_if_different
                ${CMAKE_BINARY_DIR}/compile_commands.json
                ${CMAKE_CURRENT_SOURCE_DIR}/compile_commands.json
        DEPENDS zephyr_final
        COMMENT "Copying compile_commands.json for clangd"
)