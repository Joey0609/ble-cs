/* SPDX-License-Identifier: MIT */
#include <errno.h>
#include <string.h>
#include <zephyr/kernel.h>
#include <zephyr/sys/atomic.h>
#include <zephyr/sys/byteorder.h>

#include "cs_protocol/cs_protocol_packets.h"
#if defined(CONFIG_BT_CHANNEL_SOUNDING)
#include "cs_utils/cs_capabilities.h"
#include "cs_utils/cs_reports.h"
#include "cs_utils/cs_results.h"
#endif
#include "host_link_internal.h"
#include "host_link_reports.h"

int host_link_report_client_state(uint8_t state, uint8_t operation_mode, uint8_t reason,
                                  uint8_t hci_status, int32_t error) {
	struct cs_protocol_client_state_frame_t frame = {
		.state = state,
		.operation_mode = operation_mode,
		.reason = reason,
		.hci_status = hci_status,
		.error = (int32_t)sys_cpu_to_le32((uint32_t)error),
	};

	(void)cs_protocol_finalize_frame(&frame, sizeof(frame), CS_PROTOCOL_PACKET_CLIENT_STATE);
	return host_link_send_report((const uint8_t *)&frame, sizeof(frame));
}

int host_link_report_fae_table(uint8_t hci_status, const int8_t *entries, uint8_t lsb_denominator) {
	struct cs_protocol_cs_fae_table_frame_t frame = {
		.hci_status = hci_status,
		.lsb_denominator = lsb_denominator,
	};

	if (hci_status == 0U && entries) {
		memcpy(frame.entries, entries, sizeof(frame.entries));
	}
	(void)cs_protocol_finalize_frame(&frame, sizeof(frame), CS_PROTOCOL_PACKET_CS_FAE_TABLE);
	return host_link_send_report((const uint8_t *)&frame, sizeof(frame));
}

#if defined(CONFIG_BT_CHANNEL_SOUNDING)
int host_link_report_cs_capabilities(const struct cs_capabilities *r) {
    if (!r) return -EINVAL;
    struct cs_protocol_cs_capabilities_frame_t f = {
        .source=r->source, .conn_index=r->conn_index,
        .num_config_supported=r->num_config_supported,
        .max_consecutive_procedures_supported=sys_cpu_to_le16(r->max_consecutive_procedures_supported),
        .num_antennas_supported=r->num_antennas_supported,
        .max_antenna_paths_supported=r->max_antenna_paths_supported,
        .initiator_supported=r->initiator_supported, .reflector_supported=r->reflector_supported,
        .mode_3_supported=r->mode_3_supported, .rtt_aa_only_precision=r->rtt_aa_only_precision,
        .rtt_sounding_precision=r->rtt_sounding_precision,
        .rtt_random_payload_precision=r->rtt_random_payload_precision,
        .rtt_aa_only_n=r->rtt_aa_only_n, .rtt_sounding_n=r->rtt_sounding_n,
        .rtt_random_payload_n=r->rtt_random_payload_n,
        .phase_based_nadm_sounding_supported=r->phase_based_nadm_sounding_supported,
        .phase_based_nadm_random_supported=r->phase_based_nadm_random_supported,
        .cs_sync_2m_phy_supported=r->cs_sync_2m_phy_supported,
        .cs_sync_2m_2bt_phy_supported=r->cs_sync_2m_2bt_phy_supported,
        .cs_without_fae_supported=r->cs_without_fae_supported,
        .chsel_alg_3c_supported=r->chsel_alg_3c_supported,
        .pbr_from_rtt_sounding_seq_supported=r->pbr_from_rtt_sounding_seq_supported,
        .t_ip1_times_supported=sys_cpu_to_le16(r->t_ip1_times_supported),
        .t_ip2_times_supported=sys_cpu_to_le16(r->t_ip2_times_supported),
        .t_fcs_times_supported=sys_cpu_to_le16(r->t_fcs_times_supported),
        .t_pm_times_supported=sys_cpu_to_le16(r->t_pm_times_supported),
        .t_sw_time=r->t_sw_time, .tx_snr_capability=r->tx_snr_capability,
        .t_ip2_ipt_times_supported=sys_cpu_to_le16(r->t_ip2_ipt_times_supported),
        .t_sw_ipt_time_supported=r->t_sw_ipt_time_supported,
        .cs_ipt_reflector_supported=r->cs_ipt_reflector_supported,
    };
    cs_protocol_finalize_frame(&f, sizeof(f), CS_PROTOCOL_PACKET_CS_CAPABILITIES);
    return host_link_send_report((const uint8_t *)&f, sizeof(f));
}

int host_link_report_cs_configuration(const struct cs_config_complete *r) {
    if (!r || r->status) return r ? -EIO : -EINVAL;
    struct cs_protocol_cs_configuration_frame_t f = {
        .id=r->config_id, .mode=r->mode, .min_main_mode_steps=r->min_main_mode_steps,
        .max_main_mode_steps=r->max_main_mode_steps, .main_mode_repetition=r->main_mode_repetition,
        .mode_0_steps=r->mode_0_steps, .role=r->role, .rtt_type=r->rtt_type,
        .cs_sync_phy=r->cs_sync_phy, .channel_map_repetition=r->channel_map_repetition,
        .channel_selection_type=r->channel_selection_type, .ch3c_shape=r->ch3c_shape,
        .ch3c_jump=r->ch3c_jump, .cs_enhancements_1=r->cs_enhancements_1,
        .t_ip1_time_us=r->t_ip1_time_us, .t_ip2_time_us=r->t_ip2_time_us,
        .t_fcs_time_us=r->t_fcs_time_us, .t_pm_time_us=r->t_pm_time_us,
    };
    memcpy(f.channel_map, r->channel_map, sizeof(f.channel_map));
    cs_protocol_finalize_frame(&f, sizeof(f), CS_PROTOCOL_PACKET_CS_CONFIGURATION);
    return host_link_send_report((const uint8_t *)&f, sizeof(f));
}

int host_link_report_cs_procedure(const struct cs_procedure_enable_complete *r) {
    if (!r || r->status) return r ? -EIO : -EINVAL;
    struct cs_protocol_cs_procedure_enable_complete_frame_t f = {
        .config_id=r->config_id, .state=r->state,
        .tone_antenna_config_selection=r->tone_antenna_config_selection,
        .selected_tx_power=r->selected_tx_power, .subevent_len=sys_cpu_to_le32(r->subevent_len),
        .subevents_per_event=r->subevents_per_event,
        .subevent_interval=sys_cpu_to_le16(r->subevent_interval),
        .event_interval=sys_cpu_to_le16(r->event_interval),
        .procedure_interval=sys_cpu_to_le16(r->procedure_interval),
        .procedure_count=sys_cpu_to_le16(r->procedure_count),
        .max_procedure_len=sys_cpu_to_le16(r->max_procedure_len),
    };
    cs_protocol_finalize_frame(&f, sizeof(f), CS_PROTOCOL_PACKET_CS_PROCEDURE_ENABLE_COMPLETE);
    return host_link_send_report((const uint8_t *)&f, sizeof(f));
}

/* Largest encoded step: the fixed part and a tone per antenna path plus the extension slot. */
#define ENCODED_STEP_MAX (sizeof(struct cs_protocol_cs_step_decoded_t) + \
                          CS_STEP_MAX_TONES * sizeof(struct cs_protocol_cs_tone_decoded_t))
/* Subevent frame payload before the steps. */
#define SUBEVENT_PREFIX (sizeof(struct cs_protocol_cs_initiator_subevent_result_frame_t) - \
                         CS_PROTOCOL_HEADER_SIZE)

/* One streamed subevent frame at a time (host_link_report_cs_subevent_begin()). */
static atomic_t subevent_busy;
static struct host_link_frame subevent_frame;
static uint8_t subevent_steps_left;

static void copy_packet_fields(struct cs_protocol_cs_step_decoded_t *d,
                               const struct cs_step_mode_1 *s) {
    d->channel=s->channel; d->aa_quality=s->aa_quality; d->bit_errors=s->bit_errors;
    d->nadm=s->nadm; d->antenna=s->antenna;
    if (cs_step_rssi_valid(s->rssi)) { d->flags |= CS_PROTOCOL_CS_STEP_FLAG_RSSI_VALID; d->rssi=s->rssi; }
    if (cs_step_time_difference_valid(s->time_difference)) {
        d->flags |= CS_PROTOCOL_CS_STEP_FLAG_TIME_DIFFERENCE_VALID;
        d->time_difference=(int16_t)sys_cpu_to_le16((uint16_t)s->time_difference);
    }
}

static size_t encode_step(uint8_t *dst, const struct cs_step_header *step) {
    struct cs_protocol_cs_step_decoded_t *d=(void *)dst;
    const struct cs_step_tone *tones=NULL;
    uint8_t n=0;
    memset(d, 0, sizeof(*d));
    d->nadm=CS_PROTOCOL_CS_NADM_UNKNOWN;
    switch (step->type) {
    case CS_STEP_TYPE_MODE_0_INITIATOR: {
        const struct cs_step_mode_0_initiator *s=cs_step_body(step); d->mode=0; d->channel=s->channel;
        d->aa_quality=s->aa_quality; d->bit_errors=s->bit_errors; d->antenna=s->antenna;
        if (cs_step_rssi_valid(s->rssi)) { d->flags|=CS_PROTOCOL_CS_STEP_FLAG_RSSI_VALID; d->rssi=s->rssi; }
        if (cs_step_freq_offset_valid(s->measured_freq_offset)) { d->flags|=CS_PROTOCOL_CS_STEP_FLAG_FREQ_OFFSET_VALID; d->measured_freq_offset=sys_cpu_to_le16(s->measured_freq_offset); }
        break;
    }
    case CS_STEP_TYPE_MODE_0_REFLECTOR: {
        const struct cs_step_mode_0_reflector *s=cs_step_body(step); d->mode=0; d->channel=s->channel;
        d->aa_quality=s->aa_quality; d->bit_errors=s->bit_errors; d->antenna=s->antenna;
        if (cs_step_rssi_valid(s->rssi)) { d->flags|=CS_PROTOCOL_CS_STEP_FLAG_RSSI_VALID; d->rssi=s->rssi; }
        break;
    }
    case CS_STEP_TYPE_MODE_1:
        d->mode=1; copy_packet_fields(d, cs_step_body(step)); break;
    case CS_STEP_TYPE_MODE_1_SS_RTT: {
        const struct cs_step_mode_1_ss_rtt *s=cs_step_body(step); d->mode=1;
        copy_packet_fields(d, (const struct cs_step_mode_1 *)s);
        d->flags|=CS_PROTOCOL_CS_STEP_FLAG_PCT_VALID;
        d->pct1_i=sys_cpu_to_le16(s->pct1.i); d->pct1_q=sys_cpu_to_le16(s->pct1.q);
        d->pct2_i=sys_cpu_to_le16(s->pct2.i); d->pct2_q=sys_cpu_to_le16(s->pct2.q); break;
    }
    case CS_STEP_TYPE_MODE_2: {
        const struct cs_step_mode_2 *s=cs_step_body(step); d->mode=2; d->channel=s->channel;
        d->antenna_permutation_index=s->antenna_permutation_index; tones=cs_step_tones(step,&n); break;
    }
    case CS_STEP_TYPE_MODE_3: {
        const struct cs_step_mode_3 *s=cs_step_body(step); d->mode=3;
        copy_packet_fields(d,(const struct cs_step_mode_1 *)s);
        d->antenna_permutation_index=s->antenna_permutation_index; tones=cs_step_tones(step,&n); break;
    }
    case CS_STEP_TYPE_MODE_3_SS_RTT: {
        const struct cs_step_mode_3_ss_rtt *s=cs_step_body(step); d->mode=3;
        copy_packet_fields(d,(const struct cs_step_mode_1 *)s);
        d->flags|=CS_PROTOCOL_CS_STEP_FLAG_PCT_VALID;
        d->pct1_i=sys_cpu_to_le16(s->pct1.i); d->pct1_q=sys_cpu_to_le16(s->pct1.q);
        d->pct2_i=sys_cpu_to_le16(s->pct2.i); d->pct2_q=sys_cpu_to_le16(s->pct2.q);
        d->antenna_permutation_index=s->antenna_permutation_index; tones=cs_step_tones(step,&n); break;
    }
    default: return 0;
    }
    d->num_tones=n;
    struct cs_protocol_cs_tone_decoded_t *out=(void *)(dst+sizeof(*d));
    for (uint8_t i=0; i<n; ++i) {
        out[i]=(struct cs_protocol_cs_tone_decoded_t){
            .i=(int16_t)sys_cpu_to_le16((uint16_t)tones[i].iq.i),
            .q=(int16_t)sys_cpu_to_le16((uint16_t)tones[i].iq.q),
            .antenna_path=tones[i].antenna_path, .quality=tones[i].quality,
            .extension=tones[i].extension,
        };
    }
    return sizeof(*d)+(size_t)n*sizeof(*out);
}

int host_link_report_cs_subevent_begin(const struct cs_subevent *header, uint16_t num_tones) {
    struct cs_protocol_cs_initiator_subevent_result_frame_t f;
    uint16_t type;
    size_t payload_len;
    int err;

    if (!header) {
        return -EINVAL;
    }
    if (!atomic_cas(&subevent_busy, 0, 1)) {
        return -EBUSY;
    }
    /* Size and step count go into the header, so the whole frame is sized up front. */
    payload_len = SUBEVENT_PREFIX +
                  (size_t)header->num_steps * sizeof(struct cs_protocol_cs_step_decoded_t) +
                  (size_t)num_tones * sizeof(struct cs_protocol_cs_tone_decoded_t);
    type = header->role == BT_CONN_LE_CS_ROLE_INITIATOR ?
        CS_PROTOCOL_PACKET_CS_INITIATOR_SUBEVENT_RESULT : CS_PROTOCOL_PACKET_CS_REFLECTOR_SUBEVENT_RESULT;
    err = host_link_frame_begin(&subevent_frame, &host_link_report_sink, type, payload_len);
    if (err) {
        atomic_clear(&subevent_busy);
        return err;
    }
    f = (struct cs_protocol_cs_initiator_subevent_result_frame_t){
        .config_id = header->config_id,
        .start_acl_conn_event = sys_cpu_to_le16(header->event_id),
        .procedure_counter = sys_cpu_to_le16(header->procedure_id),
        .frequency_compensation = sys_cpu_to_le16(header->frequency_compensation),
        .reference_power_level = header->reference_power_level,
        .procedure_done_status = header->procedure_done_status,
        .subevent_done_status = header->subevent_done_status,
        .procedure_abort_reason = header->procedure_abort_reason,
        .subevent_abort_reason = header->subevent_abort_reason,
        .num_antenna_paths = header->num_antenna_paths,
        .num_steps_reported = header->num_steps,
        .abort_step = header->abort_step,
    };
    host_link_frame_write(&subevent_frame, (const uint8_t *)&f + CS_PROTOCOL_HEADER_SIZE,
                          SUBEVENT_PREFIX);
    subevent_steps_left = header->num_steps;
    return 0;
}

void host_link_report_cs_subevent_step(const struct cs_step_header *step) {
    uint8_t encoded[ENCODED_STEP_MAX];
    size_t len;

    if (!step || !atomic_get(&subevent_busy) || subevent_steps_left == 0U) {
        return;
    }
    len = encode_step(encoded, step);
    host_link_frame_write(&subevent_frame, encoded, len);
    subevent_steps_left--;
}

int host_link_report_cs_subevent_end(void) {
    int err;

    if (!atomic_get(&subevent_busy)) {
        return -EINVAL;
    }
    /* A step count or tone count that disagrees with begin leaves the frame
     * short or long; either way it is sent with an invalid CRC.
     */
    err = host_link_frame_end(&subevent_frame, subevent_steps_left == 0U &&
                                               subevent_frame.payload_remaining == 0U);
    atomic_clear(&subevent_busy);
    return err;
}

int host_link_report_cs_subevent(const struct cs_subevent *r) {
    uint16_t num_tones = 0U;
    int err;

    if (!r) {
        return -EINVAL;
    }
    for (const struct cs_step_header *s = cs_step_first(r); s; s = cs_step_next(r, s)) {
        uint8_t n;

        (void)cs_step_tones(s, &n);
        num_tones += n;
    }
    err = host_link_report_cs_subevent_begin(r, num_tones);
    if (err) {
        return err;
    }
    for (const struct cs_step_header *s = cs_step_first(r); s; s = cs_step_next(r, s)) {
        host_link_report_cs_subevent_step(s);
    }
    return host_link_report_cs_subevent_end();
}
#endif /* CONFIG_BT_CHANNEL_SOUNDING */

int host_link_report_ras_data_lost(uint16_t ranging_counter, int16_t error) {
	struct cs_protocol_ras_data_lost_frame_t frame = {
		.ranging_counter = sys_cpu_to_le16(ranging_counter),
		.error = (int16_t)sys_cpu_to_le16((uint16_t)error),
	};

	(void)cs_protocol_finalize_frame(&frame, sizeof(frame), CS_PROTOCOL_PACKET_RAS_DATA_LOST);
	return host_link_send_report((const uint8_t *)&frame, sizeof(frame));
}

int host_link_report_cs_procedures_complete(uint16_t procedures_completed) {
	struct cs_protocol_cs_procedures_complete_frame_t frame = {
		.procedures_completed = sys_cpu_to_le16(procedures_completed),
	};

	(void)cs_protocol_finalize_frame(&frame, sizeof(frame),
	                                 CS_PROTOCOL_PACKET_CS_PROCEDURES_COMPLETE);
	return host_link_send_report((const uint8_t *)&frame, sizeof(frame));
}

int host_link_report_peer_data(uint8_t peer_data) {
	struct cs_protocol_cs_peer_data_frame_t frame = {
		.peer_data = peer_data,
	};

	(void)cs_protocol_finalize_frame(&frame, sizeof(frame), CS_PROTOCOL_PACKET_CS_PEER_DATA);
	return host_link_send_report((const uint8_t *)&frame, sizeof(frame));
}

int host_link_report_connection_parameters(uint16_t interval, uint16_t latency,
                                           uint16_t timeout, uint16_t mtu) {
	struct cs_protocol_connection_parameters_frame_t frame = {
		.interval = sys_cpu_to_le16(interval),
		.latency = sys_cpu_to_le16(latency),
		.timeout = sys_cpu_to_le16(timeout),
		.mtu = sys_cpu_to_le16(mtu),
	};

	(void)cs_protocol_finalize_frame(&frame, sizeof(frame),
	                                 CS_PROTOCOL_PACKET_CONNECTION_PARAMETERS);
	return host_link_send_report((const uint8_t *)&frame, sizeof(frame));
}

int host_link_report_radio_test_stats(uint32_t packets_received, uint32_t crc_errors,
                                      int8_t rssi_dbm, uint8_t channel) {
	struct cs_protocol_radio_test_stats_frame_t frame = {
		.packets_received = sys_cpu_to_le32(packets_received),
		.crc_errors = sys_cpu_to_le32(crc_errors),
		.rssi_dbm = rssi_dbm,
		.channel = channel,
	};

	(void)cs_protocol_finalize_frame(&frame, sizeof(frame), CS_PROTOCOL_PACKET_RADIO_TEST_STATS);
	return host_link_send_report((const uint8_t *)&frame, sizeof(frame));
}

int host_link_report_frame(const uint8_t *frame, size_t len) {
	if (!frame || len < CS_PROTOCOL_OVERHEAD) {
		return -EINVAL;
	}
	return host_link_send_report(frame, len);
}

void host_link_report_stats_get(struct host_link_report_stats *stats) {
	host_link_report_counters(&stats->sent, &stats->dropped);
}
