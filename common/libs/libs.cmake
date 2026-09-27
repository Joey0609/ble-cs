# SPDX-License-Identifier: MIT
# Include after find_package(Zephyr), when resolved CONFIG_* values are available.
# Set APP_LIBS_RADIO_TEST=ON before including to opt into the NCS radio helpers.
include_guard(GLOBAL)

function(app_libs_require feature)
    foreach(symbol IN LISTS ARGN)
        if(NOT ${symbol})
            message(FATAL_ERROR "${feature} requires ${symbol}=y")
        endif()
    endforeach()
endfunction()

function(app_libs_require_range symbol minimum maximum)
    if(NOT DEFINED ${symbol} OR NOT "${${symbol}}" MATCHES "^[0-9]+$")
        message(FATAL_ERROR "${symbol} must be an integer in ${minimum}..${maximum}")
    endif()
    if(${symbol} LESS minimum OR ${symbol} GREATER maximum)
        message(FATAL_ERROR "${symbol} must be in ${minimum}..${maximum} (got ${${symbol}})")
    endif()
endfunction()

# cs_protocol is available to every consumer, including non-Bluetooth builds.
app_libs_require("cs_protocol CRC-32 framing" CONFIG_CRC)

add_library(app_libs INTERFACE)
target_include_directories(app_libs INTERFACE ${CMAKE_CURRENT_LIST_DIR})
target_sources(app_libs INTERFACE
    ${CMAKE_CURRENT_LIST_DIR}/cs_protocol/cs_protocol.c
)

if(CONFIG_BT_CHANNEL_SOUNDING_TEST AND NOT CONFIG_BT_CHANNEL_SOUNDING)
    message(FATAL_ERROR "CONFIG_BT_CHANNEL_SOUNDING_TEST requires CONFIG_BT_CHANNEL_SOUNDING=y")
endif()

# Connected CS settings and reports. Do not impose a particular ACL
# role or require RAS: these helpers support both initiators and reflectors.
if(CONFIG_BT_CHANNEL_SOUNDING)
    app_libs_require("Connected CS configuration"
        CONFIG_BT CONFIG_BT_HCI_HOST CONFIG_BT_CONN CONFIG_BT_SMP)
    if(NOT CONFIG_BT_CENTRAL AND NOT CONFIG_BT_PERIPHERAL)
        message(FATAL_ERROR "Connected CS requires CONFIG_BT_CENTRAL or CONFIG_BT_PERIPHERAL")
    endif()
    app_libs_require_range(CONFIG_BT_MAX_CONN 1 255)
    app_libs_require_range(CONFIG_BT_CHANNEL_SOUNDING_REASSEMBLY_BUFFER_SIZE 239 5600)
    app_libs_require_range(CONFIG_BT_CHANNEL_SOUNDING_REASSEMBLY_BUFFER_CNT 1 ${CONFIG_BT_MAX_CONN})

    # External HCI controllers are validated at runtime. For a local controller,
    # fail at configure time if the host requests features it cannot provide.
    if(CONFIG_BT_CTLR OR CONFIG_BT_LL_SOFTDEVICE)
        app_libs_require("Local CS controller"
            CONFIG_BT_CTLR_CHANNEL_SOUNDING_SUPPORT CONFIG_BT_CTLR_CHANNEL_SOUNDING)
        if(CONFIG_BT_CHANNEL_SOUNDING_TEST)
            app_libs_require("Host CS test commands" CONFIG_BT_CTLR_CHANNEL_SOUNDING_TEST)
        endif()
    endif()
    if(CONFIG_BT_LL_SOFTDEVICE)
        set(cs_role_count 0)
        foreach(role CONFIG_BT_CTLR_SDC_CS_ROLE_BOTH
                     CONFIG_BT_CTLR_SDC_CS_ROLE_INITIATOR_ONLY
                     CONFIG_BT_CTLR_SDC_CS_ROLE_REFLECTOR_ONLY)
            if(${role})
                math(EXPR cs_role_count "${cs_role_count} + 1")
            endif()
        endforeach()
        if(NOT cs_role_count EQUAL 1)
            message(FATAL_ERROR "Select exactly one CONFIG_BT_CTLR_SDC_CS_ROLE_* option")
        endif()
        app_libs_require_range(CONFIG_BT_CTLR_SDC_CS_COUNT 1 ${CONFIG_BT_MAX_CONN})
        app_libs_require_range(CONFIG_BT_CTLR_SDC_CS_MAX_ANTENNA_PATHS 1 4)
        app_libs_require_range(CONFIG_BT_CTLR_SDC_CS_NUM_ANTENNAS 1
                              ${CONFIG_BT_CTLR_SDC_CS_MAX_ANTENNA_PATHS})
        if(CONFIG_BT_CTLR_SDC_CS_NUM_ANTENNAS GREATER 1)
            app_libs_require("Multiple CS antennas"
                CONFIG_BT_CTLR_SDC_CS_MULTIPLE_ANTENNA_SUPPORT CONFIG_GPIO)
        endif()
        # Optional mode-3 and CS test support may be enabled or disabled.
        # Their enum choices/ranges are validated by the SDK Kconfig itself.
        if(NOT CONFIG_BT_CTLR_SDC_CS_T_PM_LEN_DEFAULT MATCHES "^(10|20|40)$")
            message(FATAL_ERROR "CONFIG_BT_CTLR_SDC_CS_T_PM_LEN_DEFAULT must be 10, 20 or 40 us")
        endif()
    endif()
    target_sources(app_libs INTERFACE
        ${CMAKE_CURRENT_LIST_DIR}/cs_utils/cs_capabilities.c
        ${CMAKE_CURRENT_LIST_DIR}/cs_utils/cs_config.c
        ${CMAKE_CURRENT_LIST_DIR}/cs_utils/cs_results.c
        ${CMAKE_CURRENT_LIST_DIR}/cs_utils/cs_reports.c
        ${CMAKE_CURRENT_LIST_DIR}/cs_utils/cs_print.c
    )
endif()

if(APP_LIBS_RADIO_TEST)
    message(STATUS "APP_LIBS_RADIO_TEST: enabling NCS radio test mode helpers")
    # radio_test.h includes fem_al.h even when no physical FEM is enabled.
    app_libs_require("NCS radio test mode" CONFIG_FEM_AL_LIB CONFIG_CLOCK_CONTROL_NRF)
    if(CONFIG_BT)
        message(FATAL_ERROR "APP_LIBS_RADIO_TEST cannot share RADIO with CONFIG_BT")
    endif()
    # FEM deliberately selects MPSL + MPSL_FEM_ONLY; full MPSL owns RADIO/TIMER.
    if(CONFIG_MPSL AND NOT CONFIG_MPSL_FEM_ONLY)
        message(FATAL_ERROR "APP_LIBS_RADIO_TEST requires MPSL disabled or CONFIG_MPSL_FEM_ONLY=y")
    endif()
    if(CONFIG_FEM)
        app_libs_require("Radio test FEM support"
            CONFIG_MPSL CONFIG_MPSL_FEM_ONLY CONFIG_MPSL_FEM_ANY_SUPPORT)
        if(NOT CONFIG_MPSL_FEM_NRF21540_GPIO AND
           NOT CONFIG_MPSL_FEM_NRF21540_GPIO_SPI AND
           NOT CONFIG_MPSL_FEM_SIMPLE_GPIO AND
           NOT CONFIG_MPSL_FEM_NRF2220 AND NOT CONFIG_MPSL_FEM_NRF2240)
            message(FATAL_ERROR "CONFIG_FEM requires a supported MPSL FEM backend")
        endif()
    endif()
    if(NOT EXISTS "${ZEPHYR_NRF_MODULE_DIR}/samples/peripheral/radio_test/src/radio_test.h")
        message(FATAL_ERROR "APP_LIBS_RADIO_TEST requires the NCS radio_test sample headers")
    endif()
    target_sources(app_libs INTERFACE
        ${CMAKE_CURRENT_LIST_DIR}/radio_test_utils/radio_test_mode.c
    )
    target_include_directories(app_libs INTERFACE
        ${ZEPHYR_NRF_MODULE_DIR}/samples/peripheral/radio_test/src
    )
    target_compile_definitions(app_libs INTERFACE APP_LIBS_RADIO_TEST=1)
endif()

# Application log (common/libs/Kconfig): selected by the role and host link
# libraries, enabled by applications that use neither.
if(CONFIG_APP_LOG)
    target_sources(app_libs INTERFACE
        ${CMAKE_CURRENT_LIST_DIR}/app_log/app_log.c
        ${CMAKE_CURRENT_LIST_DIR}/app_log/app_log_console.c
    )
endif()

# Generated configuration interface (common/libs/Kconfig). The weak
# cs_generated_config.c is replaced by a planner export when the application
# compiles one.
if(CONFIG_APP_CS_GENERATED_CONFIG)
    target_sources(app_libs INTERFACE
        ${CMAKE_CURRENT_LIST_DIR}/cs_generated_config/cs_generated_config.c
    )
endif()

# CS role library (common/libs/Kconfig): connection, CS and RAS sequencing for
# cs_client and the hostless applications. Each role option adds its sources,
# so a hostless image contains only the RAS role it uses.
if(CONFIG_APP_CS_ROLES)
    if(NOT CONFIG_APP_CS_ROLES_INITIATOR AND NOT CONFIG_APP_CS_ROLES_REFLECTOR)
        message(FATAL_ERROR "CONFIG_APP_CS_ROLES needs CONFIG_APP_CS_ROLES_INITIATOR and/or CONFIG_APP_CS_ROLES_REFLECTOR")
    endif()
    # Link encryption; the GAP role (central scans and connects, peripheral
    # advertises with extended advertising for the whole name) is the application's.
    app_libs_require("CS role library" CONFIG_BT_SMP)
    if(CONFIG_BT_PERIPHERAL)
        app_libs_require("CS role library advertising" CONFIG_BT_EXT_ADV)
    endif()
    target_sources(app_libs INTERFACE
        ${CMAKE_CURRENT_LIST_DIR}/cs_roles/cs_role_core.c
        ${CMAKE_CURRENT_LIST_DIR}/cs_roles/cs_role_events.c
        ${CMAKE_CURRENT_LIST_DIR}/cs_roles/cs_role_link.c
    )
    if(CONFIG_APP_CS_ROLES_INITIATOR)
        target_sources(app_libs INTERFACE
            ${CMAKE_CURRENT_LIST_DIR}/cs_roles/cs_role_initiator.c
            ${CMAKE_CURRENT_LIST_DIR}/cs_roles/cs_role_controller.c
            ${CMAKE_CURRENT_LIST_DIR}/cs_roles/cs_ras.c
        )
    endif()
    if(CONFIG_APP_CS_ROLES_REFLECTOR)
        target_sources(app_libs INTERFACE
            ${CMAKE_CURRENT_LIST_DIR}/cs_roles/cs_role_reflector.c
        )
    endif()
endif()

# Host link (common/libs/Kconfig). Its Kconfig selects CRC, ring buffer and the
# interrupt-driven UART API; the UART (USB CDC ACM or hardware) is the
# application's choice. Only CDC ACM reports DTR.
if(CONFIG_APP_HOST_LINK)
    if(CONFIG_APP_HOST_LINK_DTR)
        app_libs_require("Host link port tracking (DTR) over USB CDC ACM"
            CONFIG_USB_DEVICE_STACK_NEXT CONFIG_USBD_CDC_ACM_CLASS)
    endif()
    if(NOT CONFIG_BT_CHANNEL_SOUNDING AND NOT APP_LIBS_RADIO_TEST)
        message(FATAL_ERROR "CONFIG_APP_HOST_LINK needs Channel Sounding or APP_LIBS_RADIO_TEST")
    endif()
    target_sources(app_libs INTERFACE
        ${CMAKE_CURRENT_LIST_DIR}/host_link/host_link.c
        ${CMAKE_CURRENT_LIST_DIR}/host_link/host_link_config.c
        ${CMAKE_CURRENT_LIST_DIR}/host_link/host_link_config_store.c
        ${CMAKE_CURRENT_LIST_DIR}/host_link/host_link_frame.c
        ${CMAKE_CURRENT_LIST_DIR}/host_link/host_link_names.c
        ${CMAKE_CURRENT_LIST_DIR}/host_link/host_link_reports.c
        ${CMAKE_CURRENT_LIST_DIR}/host_link/host_link_transport.c
    )
endif()
