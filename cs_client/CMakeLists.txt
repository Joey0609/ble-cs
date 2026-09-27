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
