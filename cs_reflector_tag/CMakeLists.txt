# SPDX-License-Identifier: MIT
cmake_minimum_required(VERSION 3.20.0)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)
set(USE_CCACHE 0)
find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})
project(cs_reflector_tag)

if(NOT CONFIG_BOARD_NRF54L15TAG OR NOT CONFIG_SOC_NRF54L15_CPUAPP)
    message(FATAL_ERROR "Build for nrf54l15tag/nrf54l15/cpuapp")
endif()

include(${CMAKE_CURRENT_SOURCE_DIR}/../common/libs/libs.cmake)
target_link_libraries(app PRIVATE app_libs)
target_sources(app PRIVATE src/main.c src/test_cfg.c)

# Optional planner export (cs_generated_config.h): config/cs_generated_config.c
# when it exists, or -DCS_CONFIG_SOURCE=<path>.c with or without sysbuild, as in
# the hostless applications; a relative path is resolved against this directory.
# Its strong definitions replace the weak defaults from
# common/libs/cs_generated_config, which leave the TEST_* values of
# src/test_cfg.c in effect. A -DCS_CONFIG_SOURCE value is cached and takes
# precedence: pass -DCS_CONFIG_SOURCE= (empty) or build pristine to return to
# config/ or the TEST_* values.
zephyr_get(CS_CONFIG_SOURCE)
if(NOT CS_CONFIG_SOURCE AND EXISTS ${CMAKE_CURRENT_SOURCE_DIR}/config/cs_generated_config.c)
    set(CS_CONFIG_SOURCE ${CMAKE_CURRENT_SOURCE_DIR}/config/cs_generated_config.c)
endif()
if(CS_CONFIG_SOURCE)
    get_filename_component(CS_CONFIG_SOURCE_ABS "${CS_CONFIG_SOURCE}" ABSOLUTE
                           BASE_DIR "${CMAKE_CURRENT_SOURCE_DIR}")
    if(NOT EXISTS "${CS_CONFIG_SOURCE_ABS}")
        message(FATAL_ERROR "CS_CONFIG_SOURCE does not exist: ${CS_CONFIG_SOURCE_ABS}")
    endif()
    message(STATUS "Planner configuration: ${CS_CONFIG_SOURCE_ABS}")
    target_sources(app PRIVATE "${CS_CONFIG_SOURCE_ABS}")
else()
    message(STATUS "Planner configuration: none, TEST_* values in src/test_cfg.c")
endif()

# Keep the compilation database where clangd discovers it automatically.
add_custom_target(copy_compile_commands ALL
        COMMAND ${CMAKE_COMMAND} -E copy_if_different
                ${CMAKE_BINARY_DIR}/compile_commands.json
                ${CMAKE_CURRENT_SOURCE_DIR}/compile_commands.json
        DEPENDS zephyr_final
        COMMENT "Copying compile_commands.json for clangd"
)

# Export after HEX generation, including builds with no source changes.
if(CONFIG_BUILD_OUTPUT_HEX)
    set(CS_HEX_EXPORT_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../bin")
    set(CS_HEX_EXPORT_FILE "${CS_HEX_EXPORT_DIR}/${PROJECT_NAME}_${BOARD}.hex")
    add_custom_target(cs_export_hex ALL
        COMMAND ${CMAKE_COMMAND} -E make_directory "${CS_HEX_EXPORT_DIR}"
        COMMAND ${CMAKE_COMMAND} -E copy
                "${BYPRODUCT_KERNEL_HEX_NAME}" "${CS_HEX_EXPORT_FILE}"
        DEPENDS "${BYPRODUCT_KERNEL_HEX_NAME}"
        COMMENT "Exporting firmware HEX to ${CS_HEX_EXPORT_FILE}"
        VERBATIM
    )
    add_dependencies(cs_export_hex ${logical_target_for_zephyr_elf})
endif()
