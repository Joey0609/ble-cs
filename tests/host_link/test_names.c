/* SPDX-License-Identifier: MIT */
/* Names used in LOG_MESSAGE text. */
#undef NDEBUG
#include "host_link/host_link_names.h"
#include "cs_protocol/cs_protocol_packets.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

#define EQ(a, b) assert(strcmp((a), (b)) == 0)

int main(void) {
	EQ(host_link_state_name(CS_PROTOCOL_CLIENT_STATE_IDLE), "IDLE");
	EQ(host_link_state_name(CS_PROTOCOL_CLIENT_STATE_ERROR), "ERROR");
	EQ(host_link_state_name(CS_PROTOCOL_CLIENT_STATE_LINK_CONNECTING + 1), "?");

	EQ(host_link_mode_name(CS_PROTOCOL_MODE_RADIO_TX_TEST), "RADIO_TX_TEST");
	EQ(host_link_mode_name(CS_PROTOCOL_MODE_NONE), "NONE");
	EQ(host_link_mode_name(0x03), "?");

	EQ(host_link_status_name(CS_PROTOCOL_STATUS_CONFIG_MISMATCH), "CONFIG_MISMATCH");
	EQ(host_link_status_name(0xFF), "?");

	EQ(host_link_reason_name(CS_PROTOCOL_REASON_NONE), "NONE");
	EQ(host_link_reason_name(CS_PROTOCOL_REASON_TEST_COMPLETE), "TEST_COMPLETE");
	EQ(host_link_reason_name(CS_PROTOCOL_REASON_INTERRUPTED), "INTERRUPTED");
	EQ(host_link_reason_name(CS_PROTOCOL_REASON_PEER_IPT_UNSUPPORTED), "PEER_IPT_UNSUPPORTED");
	EQ(host_link_reason_name(CS_PROTOCOL_REASON_PEER_IPT_UNSUPPORTED + 1), "?");

	EQ(host_link_command_name(CS_PROTOCOL_PACKET_SET_OPERATION_MODE), "SET_OPERATION_MODE");
	EQ(host_link_command_name(CS_PROTOCOL_PACKET_LINK_DISCONNECT), "LINK_DISCONNECT");
	EQ(host_link_command_name(CS_PROTOCOL_PACKET_LOG_MESSAGE), "?");
	EQ(host_link_command_name(CS_PROTOCOL_PACKET_SET_PEER_DATA), "SET_PEER_DATA");
	EQ(host_link_command_name(CS_PROTOCOL_PACKET_SET_LOG_CONFIG), "SET_LOG_CONFIG");
	EQ(host_link_command_name(CS_PROTOCOL_PACKET_SET_T_PM), "SET_T_PM");
	EQ(host_link_command_name(CS_PROTOCOL_PACKET_SET_T_PM + 1), "?");

	printf("host_link names: OK\n");
	return 0;
}
