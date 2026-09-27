/* SPDX-License-Identifier: MIT */
#undef NDEBUG
#include <assert.h>
#include <string.h>
#include "cs_protocol/cs_protocol.h"
#include "cs_protocol/cs_protocol_packets.h"

int main(void) {
    struct cs_protocol_peer_connect_frame_t frame = {
        .address_type = 1, .address = {'1', '2', '3', '4', '5', '6'},
    };
    struct cs_protocol_packet_t decoded;
    assert(cs_protocol_finalize_frame(&frame, sizeof(frame), CS_PROTOCOL_PACKET_PEER_CONNECT) == sizeof(frame));
    assert(cs_protocol_decode((const uint8_t *)&frame, sizeof(frame), &decoded) == 0);
    assert(decoded.type == CS_PROTOCOL_PACKET_PEER_CONNECT);
    assert(decoded.payload_len == 7);
    assert(memcmp(decoded.payload, "\x01" "123456", 7) == 0);
    struct cs_protocol_scan_result_frame_t report = {
        .address_type = 1, .address = {1,2,3,4,5,6}, .rssi_dbm = -56,
        .flags = 3, .name_length = 7, .name = "Peer \xc3\xa5",
    };
    assert(cs_protocol_finalize_frame(&report, sizeof(report), CS_PROTOCOL_PACKET_SCAN_RESULT) == sizeof(report));
    assert(cs_protocol_decode((const uint8_t *)&report, sizeof(report), &decoded) == 0);
    assert(decoded.payload_len == 264);
    assert(memcmp(decoded.payload, "\x01\x01\x02\x03\x04\x05\x06\xc8\x03\x07" "Peer \xc3\xa5", 17) == 0);
    struct cs_protocol_connection_parameters_frame_t connection = {
        .interval = 14, .latency = 0, .timeout = 400, .mtu = 498,
    };
    assert(cs_protocol_finalize_frame(&connection, sizeof(connection),
                                      CS_PROTOCOL_PACKET_CONNECTION_PARAMETERS) == sizeof(connection));
    assert(cs_protocol_decode((const uint8_t *)&connection, sizeof(connection), &decoded) == 0);
    assert(decoded.payload_len == 8);
    assert(memcmp(decoded.payload, "\x0e\x00\x00\x00\x90\x01\xf2\x01", 8) == 0);
    return 0;
}
