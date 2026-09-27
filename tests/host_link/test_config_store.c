/* SPDX-License-Identifier: MIT */
/* Staging, apply and CRC rules of the host link configuration store. */
#undef NDEBUG
#include "host_link/host_link_config_store.h"
#include <assert.h>
#include <errno.h>
#include <stdio.h>
#include <string.h>

#include "config_fixture.h"

static void assert_result(struct host_link_result result, uint8_t status, uint8_t reason) {
	assert(result.status == status);
	assert(result.reason == reason);
}

static void stage_initiator(struct host_link_config_store *store) {
	host_link_config_stage_mode(store, CS_PROTOCOL_MODE_CS_INITIATOR);
	assert_result(host_link_config_check_config(store, CS_PROTOCOL_PACKET_SET_CS_INITIATOR_CONFIG),
	              CS_PROTOCOL_STATUS_OK, CS_PROTOCOL_REASON_NONE);
	host_link_config_stage_config(store, PAYLOAD(initiator), HOST_LINK_INITIATOR_PAYLOAD_SIZE);
}

static void test_crc_vector(void) {
	struct host_link_config_store store;

	host_link_config_store_init(&store);
	assert(!store.applied_valid && host_link_config_crc32(&store.applied) == 0U);

	stage_initiator(&store);
	assert(host_link_config_crc32(&store.staged) == CONFIG_CRC_VECTOR_NO_PATTERNS);

	/* A GAP central needs patterns before it can be applied. */
	assert_result(host_link_config_check_apply(&store), CS_PROTOCOL_STATUS_BAD_STATE,
	              CS_PROTOCOL_REASON_MISSING_PATTERNS);

	assert_result(host_link_config_check_patterns(&store, PAYLOAD(patterns)), CS_PROTOCOL_STATUS_OK,
	              CS_PROTOCOL_REASON_NONE);
	host_link_config_stage_patterns(&store, PAYLOAD(patterns));
	assert_result(host_link_config_check_apply(&store), CS_PROTOCOL_STATUS_OK, CS_PROTOCOL_REASON_NONE);

	host_link_config_commit(&store);
	assert(store.applied_valid);
	assert(store.applied_crc32 == CONFIG_CRC_VECTOR);
	assert(!store.staged.has_mode && !store.staged.has_patterns && store.staged.config_len == 0U);

	/* A rejected apply leaves the applied configuration unchanged. */
	assert_result(host_link_config_check_apply(&store), CS_PROTOCOL_STATUS_REJECTED,
	              CS_PROTOCOL_REASON_MISSING_CONFIG);
	assert(store.applied_crc32 == CONFIG_CRC_VECTOR);
}

static void test_staging_rules(void) {
	struct host_link_config_store store;
	struct cs_protocol_cs_reflector_config_frame_t reflector = {.gap_role = CS_PROTOCOL_GAP_PERIPHERAL};

	host_link_config_store_init(&store);

	/* Configuration and patterns need a staged mode. */
	assert_result(host_link_config_check_config(&store, CS_PROTOCOL_PACKET_SET_CS_INITIATOR_CONFIG),
	              CS_PROTOCOL_STATUS_BAD_STATE, CS_PROTOCOL_REASON_MISSING_CONFIG);
	assert_result(host_link_config_check_patterns(&store, PAYLOAD(patterns)),
	              CS_PROTOCOL_STATUS_BAD_STATE, CS_PROTOCOL_REASON_MISSING_CONFIG);

	/* Frame type must match the staged mode. */
	host_link_config_stage_mode(&store, CS_PROTOCOL_MODE_CS_REFLECTOR);
	assert_result(host_link_config_check_config(&store, CS_PROTOCOL_PACKET_SET_CS_INITIATOR_CONFIG),
	              CS_PROTOCOL_STATUS_REJECTED, CS_PROTOCOL_REASON_MODE_MISMATCH);

	/* A reflector as GAP peripheral applies without patterns. */
	assert_result(host_link_config_check_config(&store, CS_PROTOCOL_PACKET_SET_CS_REFLECTOR_CONFIG),
	              CS_PROTOCOL_STATUS_OK, CS_PROTOCOL_REASON_NONE);
	host_link_config_stage_config(&store, PAYLOAD(reflector), HOST_LINK_REFLECTOR_PAYLOAD_SIZE);
	assert_result(host_link_config_check_apply(&store), CS_PROTOCOL_STATUS_OK, CS_PROTOCOL_REASON_NONE);

	/* SET_OPERATION_MODE discards everything staged before. */
	host_link_config_stage_patterns(&store, PAYLOAD(patterns));
	host_link_config_stage_mode(&store, CS_PROTOCOL_MODE_CS_REFLECTOR);
	assert(!store.staged.has_patterns && store.staged.config_len == 0U);
	assert_result(host_link_config_check_apply(&store), CS_PROTOCOL_STATUS_REJECTED,
	              CS_PROTOCOL_REASON_MISSING_CONFIG);

	/* Patterns are refused in the radio test mode. */
	host_link_config_stage_mode(&store, CS_PROTOCOL_MODE_RADIO_TX_TEST);
	assert_result(host_link_config_check_patterns(&store, PAYLOAD(patterns)),
	              CS_PROTOCOL_STATUS_REJECTED, CS_PROTOCOL_REASON_MODE_MISMATCH);
	assert(host_link_config_mode_of_type(CS_PROTOCOL_PACKET_SET_RADIO_TX_TEST_CONFIG) ==
	       CS_PROTOCOL_MODE_RADIO_TX_TEST);
	assert(host_link_config_mode_of_type(CS_PROTOCOL_PACKET_START) < 0);
}

static void test_pattern_checks(void) {
	struct host_link_config_store store;
	struct cs_protocol_peripheral_patterns_frame_t p;

	host_link_config_store_init(&store);
	host_link_config_stage_mode(&store, CS_PROTOCOL_MODE_CS_INITIATOR);

#define CHECK_PATTERNS(status, reason)                                                                  \
	assert_result(host_link_config_check_patterns(&store, PAYLOAD(p)), (status), (reason))

	p = patterns;
	p.patterns[0][12] = 'x'; /* byte after the length */
	CHECK_PATTERNS(CS_PROTOCOL_STATUS_REJECTED, CS_PROTOCOL_REASON_NONZERO_PADDING);

	p = patterns;
	p.patterns[5][0] = 'x'; /* unused slot */
	CHECK_PATTERNS(CS_PROTOCOL_STATUS_REJECTED, CS_PROTOCOL_REASON_NONZERO_PADDING);

	p = patterns;
	p.lengths[5] = 1; /* unused length */
	CHECK_PATTERNS(CS_PROTOCOL_STATUS_REJECTED, CS_PROTOCOL_REASON_NONZERO_PADDING);

	p = patterns;
	p.count = 0;
	CHECK_PATTERNS(CS_PROTOCOL_STATUS_REJECTED, CS_PROTOCOL_REASON_VALUE_OUT_OF_RANGE);

	p = patterns;
	p.count = 9;
	CHECK_PATTERNS(CS_PROTOCOL_STATUS_REJECTED, CS_PROTOCOL_REASON_VALUE_OUT_OF_RANGE);

	p = patterns;
	p.lengths[1] = 0;
	CHECK_PATTERNS(CS_PROTOCOL_STATUS_REJECTED, CS_PROTOCOL_REASON_VALUE_OUT_OF_RANGE);

	p = patterns;
	p.lengths[1] = 33;
	CHECK_PATTERNS(CS_PROTOCOL_STATUS_REJECTED, CS_PROTOCOL_REASON_VALUE_OUT_OF_RANGE);

	p = patterns;
	p.lengths[1] = 4; /* includes the NUL after "nRF" */
	CHECK_PATTERNS(CS_PROTOCOL_STATUS_REJECTED, CS_PROTOCOL_REASON_VALUE_OUT_OF_RANGE);

	p = patterns;
	p.patterns[1][1] = 0xc3; /* truncated two-byte sequence: 'n', 0xc3, 'F' */
	CHECK_PATTERNS(CS_PROTOCOL_STATUS_REJECTED, CS_PROTOCOL_REASON_VALUE_OUT_OF_RANGE);

	p = patterns;
	memcpy(p.patterns[1], "\xc3\xa5\xe2\x82\xac", 5); /* "å€": multi-byte UTF-8 */
	p.lengths[1] = 5;
	CHECK_PATTERNS(CS_PROTOCOL_STATUS_OK, CS_PROTOCOL_REASON_NONE);

	p = patterns;
	p.count = 8;
	for (unsigned int i = 0; i < 8; i++) {
		memset(p.patterns[i], 'a' + i, 32);
		p.lengths[i] = 32;
	}
	CHECK_PATTERNS(CS_PROTOCOL_STATUS_OK, CS_PROTOCOL_REASON_NONE);
#undef CHECK_PATTERNS
}

static void test_device_name(void) {
    struct host_link_config_store store;
    const uint8_t name[33] = {5, 'B', 'o', 'a', 'r', 'd'};
    host_link_config_store_init(&store);
    assert(host_link_config_check_device_name(&store, name).status == CS_PROTOCOL_STATUS_BAD_STATE);
    host_link_config_stage_mode(&store, CS_PROTOCOL_MODE_CS_INITIATOR);
    host_link_config_stage_config(&store, PAYLOAD(initiator), HOST_LINK_INITIATOR_PAYLOAD_SIZE);
    host_link_config_stage_patterns(&store, PAYLOAD(patterns));
    assert(host_link_config_check_device_name(&store, name).status == CS_PROTOCOL_STATUS_OK);
    memcpy(store.staged.device_name, name, sizeof(name));
    store.staged.has_device_name = true;
    assert(host_link_config_crc32(&store.staged) == 0x30959349U);
    uint8_t bad[33];
    memcpy(bad, name, sizeof(bad));
    bad[32] = 1;
    assert(host_link_config_check_device_name(&store, bad).reason == CS_PROTOCOL_REASON_NONZERO_PADDING);
    bad[0] = 33;
    assert(host_link_config_check_device_name(&store, bad).reason == CS_PROTOCOL_REASON_VALUE_OUT_OF_RANGE);
    memcpy(bad, name, sizeof(bad));
    bad[1] = 0xff;
    assert(host_link_config_check_device_name(&store, bad).reason == CS_PROTOCOL_REASON_VALUE_OUT_OF_RANGE);
    host_link_config_commit(&store);
    assert(store.applied.has_device_name);
    assert(!store.staged.has_device_name);
    host_link_config_stage_mode(&store, CS_PROTOCOL_MODE_CS_INITIATOR);
    host_link_config_stage_config(&store, PAYLOAD(initiator), HOST_LINK_INITIATOR_PAYLOAD_SIZE);
    host_link_config_stage_patterns(&store, PAYLOAD(patterns));
    host_link_config_commit(&store);
    assert(!store.applied.has_device_name);
    assert(store.applied_crc32 == CONFIG_CRC_VECTOR);
}

static const uint8_t peer_data_none[HOST_LINK_PEER_DATA_PAYLOAD_SIZE] = {CS_PROTOCOL_PEER_DATA_NONE};

static void stage_initiator_ipt(struct host_link_config_store *store) {
	struct cs_protocol_cs_initiator_config_frame_t ipt = initiator;

	ipt.creation_cs_enhancements_1 = CS_PROTOCOL_CONFIG_ENHANCEMENTS_1_IPT;
	host_link_config_stage_mode(store, CS_PROTOCOL_MODE_CS_INITIATOR);
	host_link_config_stage_config(store, PAYLOAD(ipt), HOST_LINK_INITIATOR_PAYLOAD_SIZE);
	host_link_config_stage_patterns(store, PAYLOAD(patterns));
}

static void test_peer_data(void) {
	struct host_link_config_store store;
	const uint8_t ras[HOST_LINK_PEER_DATA_PAYLOAD_SIZE] = {CS_PROTOCOL_PEER_DATA_RAS_REALTIME};
	const uint8_t unknown[HOST_LINK_PEER_DATA_PAYLOAD_SIZE] = {2};

	host_link_config_store_init(&store);
	assert_result(host_link_config_check_peer_data(&store, peer_data_none),
	              CS_PROTOCOL_STATUS_BAD_STATE, CS_PROTOCOL_REASON_MISSING_CONFIG);

	/* Only the CS initiator mode has reflector data. */
	host_link_config_stage_mode(&store, CS_PROTOCOL_MODE_CS_REFLECTOR);
	assert_result(host_link_config_check_peer_data(&store, peer_data_none),
	              CS_PROTOCOL_STATUS_REJECTED, CS_PROTOCOL_REASON_MODE_MISMATCH);
	host_link_config_stage_mode(&store, CS_PROTOCOL_MODE_RADIO_TX_TEST);
	assert_result(host_link_config_check_peer_data(&store, peer_data_none),
	              CS_PROTOCOL_STATUS_REJECTED, CS_PROTOCOL_REASON_MODE_MISMATCH);

	/* RAS real-time is expressed by omitting the frame. */
	stage_initiator_ipt(&store);
	assert_result(host_link_config_check_peer_data(&store, ras), CS_PROTOCOL_STATUS_REJECTED,
	              CS_PROTOCOL_REASON_VALUE_OUT_OF_RANGE);
	assert_result(host_link_config_check_peer_data(&store, unknown), CS_PROTOCOL_STATUS_REJECTED,
	              CS_PROTOCOL_REASON_VALUE_OUT_OF_RANGE);
	assert(!store.staged.has_peer_data);

	/* Last in CRC order, after the patterns. */
	assert_result(host_link_config_check_peer_data(&store, peer_data_none), CS_PROTOCOL_STATUS_OK,
	              CS_PROTOCOL_REASON_NONE);
	host_link_config_stage_peer_data(&store, peer_data_none);
	assert(store.staged.has_peer_data && store.staged.peer_data == CS_PROTOCOL_PEER_DATA_NONE);
	assert(host_link_config_crc32(&store.staged) == CONFIG_CRC_VECTOR_PEER_DATA);
	assert_result(host_link_config_check_apply(&store), CS_PROTOCOL_STATUS_OK, CS_PROTOCOL_REASON_NONE);
	host_link_config_commit(&store);
	assert(store.applied.has_peer_data && store.applied_crc32 == CONFIG_CRC_VECTOR_PEER_DATA);
	assert(!store.staged.has_peer_data);

	/* SET_OPERATION_MODE discards it with the rest of the staging area. */
	stage_initiator_ipt(&store);
	host_link_config_stage_peer_data(&store, peer_data_none);
	host_link_config_stage_mode(&store, CS_PROTOCOL_MODE_CS_INITIATOR);
	assert(!store.staged.has_peer_data);

	/* None needs the IPT request; the applied configuration stays. */
	stage_initiator(&store);
	host_link_config_stage_patterns(&store, PAYLOAD(patterns));
	host_link_config_stage_peer_data(&store, peer_data_none);
	struct host_link_result result = host_link_config_check_apply(&store);
	assert_result(result, CS_PROTOCOL_STATUS_REJECTED, CS_PROTOCOL_REASON_VALUE_OUT_OF_RANGE);
	assert(result.error == -EINVAL);
	assert(store.applied_crc32 == CONFIG_CRC_VECTOR_PEER_DATA);

	/* Without the frame the IPT configuration keeps RAS and its own CRC. */
	stage_initiator_ipt(&store);
	assert_result(host_link_config_check_apply(&store), CS_PROTOCOL_STATUS_OK, CS_PROTOCOL_REASON_NONE);
	host_link_config_commit(&store);
	assert(!store.applied.has_peer_data);
	assert(store.applied_crc32 != CONFIG_CRC_VECTOR_PEER_DATA);
}

static const uint8_t log_debug_info[HOST_LINK_LOG_CONFIG_PAYLOAD_SIZE] = {
	CS_PROTOCOL_LOG_LEVEL_DEBUG, CS_PROTOCOL_LOG_LEVEL_INFO};

static void test_log_config(void) {
	struct host_link_config_store store;
	const uint8_t defaults[HOST_LINK_LOG_CONFIG_PAYLOAD_SIZE] = {
		CS_PROTOCOL_LOG_CONSOLE_LEVEL_DEFAULT, CS_PROTOCOL_LOG_PROTOCOL_LEVEL_DEFAULT};
	const uint8_t console_too_high[HOST_LINK_LOG_CONFIG_PAYLOAD_SIZE] = {
		CS_PROTOCOL_LOG_LEVEL_DEBUG + 1, CS_PROTOCOL_LOG_LEVEL_INFO};
	const uint8_t protocol_too_high[HOST_LINK_LOG_CONFIG_PAYLOAD_SIZE] = {
		CS_PROTOCOL_LOG_LEVEL_INFO, CS_PROTOCOL_LOG_LEVEL_DEBUG + 1};
	const uint8_t both_off[HOST_LINK_LOG_CONFIG_PAYLOAD_SIZE] = {CS_PROTOCOL_LOG_LEVEL_OFF,
	                                                             CS_PROTOCOL_LOG_LEVEL_OFF};

	host_link_config_store_init(&store);
	assert_result(host_link_config_check_log_config(&store, log_debug_info),
	              CS_PROTOCOL_STATUS_BAD_STATE, CS_PROTOCOL_REASON_MISSING_CONFIG);

	/* Every operation mode has log levels. */
	host_link_config_stage_mode(&store, CS_PROTOCOL_MODE_CS_REFLECTOR);
	assert_result(host_link_config_check_log_config(&store, log_debug_info),
	              CS_PROTOCOL_STATUS_OK, CS_PROTOCOL_REASON_NONE);
	host_link_config_stage_mode(&store, CS_PROTOCOL_MODE_RADIO_TX_TEST);
	assert_result(host_link_config_check_log_config(&store, both_off), CS_PROTOCOL_STATUS_OK,
	              CS_PROTOCOL_REASON_NONE);

	/* One byte representation: the defaults are expressed by omitting the frame. */
	stage_initiator(&store);
	host_link_config_stage_patterns(&store, PAYLOAD(patterns));
	assert_result(host_link_config_check_log_config(&store, defaults),
	              CS_PROTOCOL_STATUS_REJECTED, CS_PROTOCOL_REASON_VALUE_OUT_OF_RANGE);
	assert_result(host_link_config_check_log_config(&store, console_too_high),
	              CS_PROTOCOL_STATUS_REJECTED, CS_PROTOCOL_REASON_VALUE_OUT_OF_RANGE);
	assert_result(host_link_config_check_log_config(&store, protocol_too_high),
	              CS_PROTOCOL_STATUS_REJECTED, CS_PROTOCOL_REASON_VALUE_OUT_OF_RANGE);
	assert(!store.staged.has_log_config);
	assert(host_link_config_crc32(&store.staged) == CONFIG_CRC_VECTOR);

	/* Last in CRC order. */
	assert_result(host_link_config_check_log_config(&store, log_debug_info),
	              CS_PROTOCOL_STATUS_OK, CS_PROTOCOL_REASON_NONE);
	host_link_config_stage_log_config(&store, log_debug_info);
	assert(store.staged.has_log_config);
	assert(memcmp(store.staged.log_config, log_debug_info, sizeof(log_debug_info)) == 0);
	assert(host_link_config_crc32(&store.staged) == CONFIG_CRC_VECTOR_LOG_CONFIG);
	assert_result(host_link_config_check_apply(&store), CS_PROTOCOL_STATUS_OK, CS_PROTOCOL_REASON_NONE);
	host_link_config_commit(&store);
	assert(store.applied.has_log_config && store.applied_crc32 == CONFIG_CRC_VECTOR_LOG_CONFIG);
	assert(!store.staged.has_log_config);

	/* Staged after the peer data, it leaves the peer data CRC prefix unchanged. */
	stage_initiator_ipt(&store);
	host_link_config_stage_peer_data(&store, peer_data_none);
	host_link_config_stage_log_config(&store, log_debug_info);
	assert(host_link_config_crc32(&store.staged) != CONFIG_CRC_VECTOR_PEER_DATA);
	store.staged.has_log_config = false;
	assert(host_link_config_crc32(&store.staged) == CONFIG_CRC_VECTOR_PEER_DATA);
	store.staged.has_log_config = true;

	/* SET_OPERATION_MODE discards it with the rest of the staging area. */
	host_link_config_stage_mode(&store, CS_PROTOCOL_MODE_CS_INITIATOR);
	assert(!store.staged.has_log_config);

	/* Without the frame the configuration keeps the CRC it had before log levels existed. */
	stage_initiator(&store);
	host_link_config_stage_patterns(&store, PAYLOAD(patterns));
	assert_result(host_link_config_check_apply(&store), CS_PROTOCOL_STATUS_OK, CS_PROTOCOL_REASON_NONE);
	host_link_config_commit(&store);
	assert(!store.applied.has_log_config && store.applied_crc32 == CONFIG_CRC_VECTOR);
}

static const uint8_t t_pm_40[HOST_LINK_T_PM_PAYLOAD_SIZE] = {CS_PROTOCOL_T_PM_40_US};

static void test_t_pm(void) {
	struct host_link_config_store store;
	const uint8_t t_pm_10[HOST_LINK_T_PM_PAYLOAD_SIZE] = {CS_PROTOCOL_T_PM_10_US};
	const uint8_t t_pm_20[HOST_LINK_T_PM_PAYLOAD_SIZE] = {CS_PROTOCOL_T_PM_20_US};
	const uint8_t t_pm_30[HOST_LINK_T_PM_PAYLOAD_SIZE] = {30};
	const uint8_t t_pm_0[HOST_LINK_T_PM_PAYLOAD_SIZE] = {0};

	host_link_config_store_init(&store);
	assert_result(host_link_config_check_t_pm(&store, t_pm_40), CS_PROTOCOL_STATUS_BAD_STATE,
	              CS_PROTOCOL_REASON_MISSING_CONFIG);

	/* Only the initiator creates the configuration, so only it has a T_PM. */
	host_link_config_stage_mode(&store, CS_PROTOCOL_MODE_CS_REFLECTOR);
	assert_result(host_link_config_check_t_pm(&store, t_pm_40), CS_PROTOCOL_STATUS_REJECTED,
	              CS_PROTOCOL_REASON_MODE_MISMATCH);
	host_link_config_stage_mode(&store, CS_PROTOCOL_MODE_RADIO_TX_TEST);
	assert_result(host_link_config_check_t_pm(&store, t_pm_40), CS_PROTOCOL_STATUS_REJECTED,
	              CS_PROTOCOL_REASON_MODE_MISMATCH);

	/* 10 us is expressed by omitting the frame. */
	stage_initiator(&store);
	host_link_config_stage_patterns(&store, PAYLOAD(patterns));
	assert_result(host_link_config_check_t_pm(&store, t_pm_10), CS_PROTOCOL_STATUS_REJECTED,
	              CS_PROTOCOL_REASON_VALUE_OUT_OF_RANGE);
	assert_result(host_link_config_check_t_pm(&store, t_pm_30), CS_PROTOCOL_STATUS_REJECTED,
	              CS_PROTOCOL_REASON_VALUE_OUT_OF_RANGE);
	assert_result(host_link_config_check_t_pm(&store, t_pm_0), CS_PROTOCOL_STATUS_REJECTED,
	              CS_PROTOCOL_REASON_VALUE_OUT_OF_RANGE);
	assert(!store.staged.has_t_pm);
	assert_result(host_link_config_check_t_pm(&store, t_pm_20), CS_PROTOCOL_STATUS_OK,
	              CS_PROTOCOL_REASON_NONE);

	/* After the patterns in CRC order. */
	assert_result(host_link_config_check_t_pm(&store, t_pm_40), CS_PROTOCOL_STATUS_OK,
	              CS_PROTOCOL_REASON_NONE);
	host_link_config_stage_t_pm(&store, t_pm_40);
	assert(store.staged.has_t_pm && store.staged.t_pm_us == CS_PROTOCOL_T_PM_40_US);
	assert(host_link_config_crc32(&store.staged) == CONFIG_CRC_VECTOR_T_PM);
	assert_result(host_link_config_check_apply(&store), CS_PROTOCOL_STATUS_OK, CS_PROTOCOL_REASON_NONE);
	host_link_config_commit(&store);
	assert(store.applied.has_t_pm && store.applied_crc32 == CONFIG_CRC_VECTOR_T_PM);
	assert(!store.staged.has_t_pm);

	/* Between the peer data and the log levels: each prefix keeps its CRC. */
	stage_initiator_ipt(&store);
	host_link_config_stage_peer_data(&store, peer_data_none);
	host_link_config_stage_t_pm(&store, t_pm_40);
	host_link_config_stage_log_config(&store, log_debug_info);
	store.staged.has_log_config = false;
	store.staged.has_t_pm = false;
	assert(host_link_config_crc32(&store.staged) == CONFIG_CRC_VECTOR_PEER_DATA);
	store.staged.has_t_pm = true;
	store.staged.has_peer_data = false;
	store.staged.config[offsetof(struct cs_protocol_cs_initiator_config_frame_t,
	                             creation_cs_enhancements_1) - CS_PROTOCOL_HEADER_SIZE] = 0;
	assert(host_link_config_crc32(&store.staged) == CONFIG_CRC_VECTOR_T_PM);
	store.staged.has_log_config = true;
	assert(host_link_config_crc32(&store.staged) == CONFIG_CRC_VECTOR_T_PM_LOG_CONFIG);

	/* SET_OPERATION_MODE discards it with the rest of the staging area. */
	host_link_config_stage_mode(&store, CS_PROTOCOL_MODE_CS_INITIATOR);
	assert(!store.staged.has_t_pm);

	/* Without the frame the configuration keeps the CRC it had before T_PM existed. */
	stage_initiator(&store);
	host_link_config_stage_patterns(&store, PAYLOAD(patterns));
	assert_result(host_link_config_check_apply(&store), CS_PROTOCOL_STATUS_OK, CS_PROTOCOL_REASON_NONE);
	host_link_config_commit(&store);
	assert(!store.applied.has_t_pm && store.applied_crc32 == CONFIG_CRC_VECTOR);
}

int main(void) {
	test_device_name();
	test_peer_data();
	test_log_config();
	test_t_pm();
	test_crc_vector();
	test_staging_rules();
	test_pattern_checks();
	puts("host_link config store tests passed");
}
