# SPDX-License-Identifier: MIT
cmake_minimum_required(VERSION 3.20.0)
# Avoid archive failures with the NCS toolchain's ccache link launcher.
set(USE_CCACHE 0)
find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})
project(cs_hostless_initiator)

include(${CMAKE_CURRENT_SOURCE_DIR}/../common/libs/libs.cmake)
target_link_libraries(app PRIVATE app_libs)
target_sources(app PRIVATE
    src/main.c
)

# Planner export (cs_generated_config.h): config/cs_generated_config.c when it
# exists, or -DCS_CONFIG_SOURCE=<path>.c (with or without sysbuild). Without
# one, the weak default in common/libs/cs_generated_config is linked and the
# default configuration runs.
zephyr_get(CS_CONFIG_SOURCE)
if(NOT CS_CONFIG_SOURCE AND EXISTS ${CMAKE_CURRENT_SOURCE_DIR}/config/cs_generated_config.c)
    set(CS_CONFIG_SOURCE ${CMAKE_CURRENT_SOURCE_DIR}/config/cs_generated_config.c)
else()
    message(STATUS "Configured CS_CONFIG_SOURCE: ${CS_CONFIG_SOURCE}")
endif()
if(CS_CONFIG_SOURCE)
    get_filename_component(CS_CONFIG_SOURCE_ABS "${CS_CONFIG_SOURCE}" ABSOLUTE
                           BASE_DIR "${CMAKE_CURRENT_SOURCE_DIR}")
    if(NOT EXISTS "${CS_CONFIG_SOURCE_ABS}")
        message(FATAL_ERROR "CS_CONFIG_SOURCE does not exist: ${CS_CONFIG_SOURCE_ABS}")
    endif()
    message(STATUS "Planner configuration: ${CS_CONFIG_SOURCE_ABS}")
    target_sources(app PRIVATE "${CS_CONFIG_SOURCE_ABS}")
endif()

# Keep the compilation database where clangd discovers it automatically.
add_custom_target(copy_compile_commands ALL
        COMMAND ${CMAKE_COMMAND} -E copy_if_different
                ${CMAKE_BINARY_DIR}/compile_commands.json
                ${CMAKE_CURRENT_SOURCE_DIR}/compile_commands.json
        DEPENDS zephyr_final
        COMMENT "Copying compile_commands.json for clangd"
)
