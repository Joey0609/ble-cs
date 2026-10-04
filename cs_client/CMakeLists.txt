# SPDX-License-Identifier: MIT

cmake_minimum_required(VERSION 3.20.0)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

# Avoid archive failures with the NCS toolchain's ccache link launcher.
set(USE_CCACHE 0)

# One source tree, two builds (README.md): prj.conf is the Bluetooth build,
# -DFILE_SUFFIX=radio_test uses prj_radio_test.conf instead. Both get the shared
# settings; Zephyr merges this with any EXTRA_CONF_FILE given on the command line.
list(APPEND EXTRA_CONF_FILE common.conf)

find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})
project(cs_client)

if(NOT CONFIG_BT)
    set(APP_LIBS_RADIO_TEST ON)
endif()
include(${CMAKE_CURRENT_SOURCE_DIR}/../common/libs/libs.cmake)
target_link_libraries(app PRIVATE app_libs)

target_sources(app PRIVATE
    src/main.c
    src/client_state.c
)

if(CONFIG_BT)
    target_sources(app PRIVATE src/cs_session.c src/peer_discovery.c)
else()
    # The NCS radio test driver is used as-is; its shell front-end is not built.
    target_sources(app PRIVATE
        ${ZEPHYR_NRF_MODULE_DIR}/samples/peripheral/radio_test/src/radio_test.c
        src/radio_session.c
    )
endif()

# Keep the compilation database where clangd discovers it automatically.
add_custom_target(copy_compile_commands ALL
        COMMAND ${CMAKE_COMMAND} -E copy_if_different
                ${CMAKE_BINARY_DIR}/compile_commands.json
                ${CMAKE_CURRENT_SOURCE_DIR}/compile_commands.json
        DEPENDS zephyr_final
        COMMENT "Copying compile_commands.json for clangd"
)

# Export after HEX generation, including builds with no source changes. The
# radio test build (-DFILE_SUFFIX=radio_test) gets its own file name.
if(CONFIG_BUILD_OUTPUT_HEX)
    set(CS_HEX_EXPORT_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../bin")
    set(CS_HEX_EXPORT_NAME "${PROJECT_NAME}")
    if(FILE_SUFFIX)
        string(APPEND CS_HEX_EXPORT_NAME "_${FILE_SUFFIX}")
    endif()
    set(CS_HEX_EXPORT_FILE "${CS_HEX_EXPORT_DIR}/${CS_HEX_EXPORT_NAME}_${BOARD}.hex")
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
