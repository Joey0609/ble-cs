# SPDX-License-Identifier: MIT
cmake_minimum_required(VERSION 3.20.0)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)
find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})
project(usb_acm_rate_test)
target_sources(app PRIVATE main_usb_acm_rate_test.c)

# Refresh clangd's database even when the firmware itself needs no rebuilding.
add_custom_target(update_compile_commands ALL
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
        "${CMAKE_BINARY_DIR}/compile_commands.json"
        "${CMAKE_CURRENT_SOURCE_DIR}/compile_commands.json"
    DEPENDS zephyr_final
    COMMENT "Updating compile_commands.json in the application root"
    VERBATIM
)
