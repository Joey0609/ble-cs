# SPDX-License-Identifier: MIT
cmake_minimum_required(VERSION 3.20.0)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)
set(USE_CCACHE 0)

find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})
project(cs_tag_modulated_tx)

# if(NOT CONFIG_BOARD_NRF54L15TAG OR NOT CONFIG_SOC_NRF54L15_CPUAPP)
# 	message(FATAL_ERROR "Build for nrf54l15tag/nrf54l15/cpuapp")
# endif()

# Use Nordic's radio_test driver directly, with the shared adapter and a
# compile-time configuration. Bluetooth/MPSL cannot own the radio concurrently.
set(NCS_RADIO_TEST_DIR ${ZEPHYR_NRF_MODULE_DIR}/samples/peripheral/radio_test/src)
set(APP_LIBS_RADIO_TEST ON)
include(${CMAKE_CURRENT_SOURCE_DIR}/../common/libs/libs.cmake)
target_link_libraries(app PRIVATE app_libs)
target_sources(app PRIVATE
	${NCS_RADIO_TEST_DIR}/radio_test.c
	src/main.c
	src/test_cfg.c
)
target_include_directories(app PRIVATE ${NCS_RADIO_TEST_DIR})

add_custom_target(copy_compile_commands ALL
	COMMAND ${CMAKE_COMMAND} -E copy_if_different
		${CMAKE_BINARY_DIR}/compile_commands.json
		${CMAKE_CURRENT_SOURCE_DIR}/compile_commands.json
	DEPENDS zephyr_final
	COMMENT "Copying compile_commands.json for clangd"
)
