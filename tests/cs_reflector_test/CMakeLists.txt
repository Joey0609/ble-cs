# SPDX-License-Identifier: MIT

cmake_minimum_required(VERSION 3.20.0)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

# Avoid archive failures with the NCS toolchain's ccache link launcher.
set(USE_CCACHE 0)

find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})
project(cs_reflector_test)

include(${CMAKE_CURRENT_SOURCE_DIR}/../../common/libs/libs.cmake)
target_link_libraries(app PRIVATE app_libs)

target_sources(app PRIVATE
    src/main.c
    src/test_cfg.c
    src/cs_events.c
    src/record_queue.c
    src/report_printer.c
    src/cdc_out.c
)

# Keep the compilation database where clangd discovers it automatically.
add_custom_target(copy_compile_commands ALL
        COMMAND ${CMAKE_COMMAND} -E copy_if_different
                ${CMAKE_BINARY_DIR}/compile_commands.json
                ${CMAKE_CURRENT_SOURCE_DIR}/compile_commands.json
        DEPENDS zephyr_final
        COMMENT "Copying compile_commands.json for clangd"
)
