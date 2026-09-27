/* SPDX-License-Identifier: MIT */
#include <errno.h>
#include <stddef.h>
#include <zephyr/bluetooth/conn.h>

#include "cs_capabilities.h"
#include "cs_print_internal.h"
#include "cs_reports.h"

/* The record is transmitted as raw bytes, so its size and the offsets of the
 * header fields a reader relies on are part of the contract.
 */
BUILD_ASSERT(sizeof(struct cs_capabilities) == 47U);
BUILD_ASSERT(offsetof(struct cs_capabilities, source) == 0U);
BUILD_ASSERT(offsetof(struct cs_capabilities, size) == 1U);
BUILD_ASSERT(offsetof(struct cs_capabilities, timestamp_us) == 4U);
BUILD_ASSERT(sizeof(struct cs_capabilities) <= UINT8_MAX);

int cs_capabilities_pack(struct cs_capabilities *dst,
			 const struct bt_conn *conn,
			 const struct bt_conn_le_cs_capabilities *src,
			 uint64_t timestamp_us) {
	if (!dst || !src) {
		return -EINVAL;
	}
	*dst = (struct cs_capabilities){
		.source = conn ? CS_CAPABILITIES_SOURCE_REMOTE : CS_CAPABILITIES_SOURCE_LOCAL,
		.size = sizeof(struct cs_capabilities),
		.conn_index = conn ? bt_conn_index(conn) : CS_CAPABILITIES_CONN_NONE,
		.timestamp_us = timestamp_us ? timestamp_us : cs_subevent_timestamp_us(),
		.max_consecutive_procedures_supported = src->max_consecutive_procedures_supported,
		.t_ip1_times_supported = src->t_ip1_times_supported,
		.t_ip2_times_supported = src->t_ip2_times_supported,
		.t_fcs_times_supported = src->t_fcs_times_supported,
		.t_pm_times_supported = src->t_pm_times_supported,
		.t_ip2_ipt_times_supported = src->t_ip2_ipt_times_supported,
		.num_config_supported = src->num_config_supported,
		.num_antennas_supported = src->num_antennas_supported,
		.max_antenna_paths_supported = src->max_antenna_paths_supported,
		.initiator_supported = src->initiator_supported ? 1U : 0U,
		.reflector_supported = src->reflector_supported ? 1U : 0U,
		.mode_3_supported = src->mode_3_supported ? 1U : 0U,
		.rtt_aa_only_precision = (uint8_t)src->rtt_aa_only_precision,
		.rtt_sounding_precision = (uint8_t)src->rtt_sounding_precision,
		.rtt_random_payload_precision = (uint8_t)src->rtt_random_payload_precision,
		.rtt_aa_only_n = src->rtt_aa_only_n,
		.rtt_sounding_n = src->rtt_sounding_n,
		.rtt_random_payload_n = src->rtt_random_payload_n,
		.phase_based_nadm_sounding_supported =
			src->phase_based_nadm_sounding_supported ? 1U : 0U,
		.phase_based_nadm_random_supported =
			src->phase_based_nadm_random_supported ? 1U : 0U,
		.cs_sync_2m_phy_supported = src->cs_sync_2m_phy_supported ? 1U : 0U,
		.cs_sync_2m_2bt_phy_supported = src->cs_sync_2m_2bt_phy_supported ? 1U : 0U,
		.cs_without_fae_supported = src->cs_without_fae_supported ? 1U : 0U,
		.chsel_alg_3c_supported = src->chsel_alg_3c_supported ? 1U : 0U,
		.pbr_from_rtt_sounding_seq_supported =
			src->pbr_from_rtt_sounding_seq_supported ? 1U : 0U,
		.cs_ipt_reflector_supported = src->cs_ipt_reflector ? 1U : 0U,
		.t_sw_time = src->t_sw_time,
		.tx_snr_capability = src->tx_snr_capability,
		.t_sw_ipt_time_supported = src->t_sw_ipt_time_supported,
	};
	return 0;
}

int cs_capabilities_read_local(struct cs_capabilities *dst) {
	/* Zeroed because V1 does not write the IPT fields at all. */
	struct bt_conn_le_cs_capabilities local = {0};
	uint64_t timestamp_us;
	int err;

	if (!dst) {
		return -EINVAL;
	}
	timestamp_us = cs_subevent_timestamp_us();

	/* Both calls return a negative errno for a failed command and the positive
	 * HCI status from the response otherwise.
	 */
	err = bt_le_cs_read_local_supported_capabilities_v2(&local);
	if (err) {
		local = (struct bt_conn_le_cs_capabilities){0};
		err = bt_le_cs_read_local_supported_capabilities(&local);
	}
	if (err > 0) {
		return -EIO;
	}
	if (err) {
		return err;
	}
	return cs_capabilities_pack(dst, NULL, &local, timestamp_us);
}

int cs_capabilities_print(char *buf, size_t size, const struct cs_capabilities *caps) {
	struct cs_print_buf pb;

	if (!caps || cs_print_init(&pb, buf, size)) {
		return -EINVAL;
	}
	if (caps->source == CS_CAPABILITIES_SOURCE_REMOTE) {
		cs_print_append(&pb, "CS capabilities (remote, connection %u, t=%llu us):\n",
		                (unsigned int)caps->conn_index,
		                (unsigned long long)caps->timestamp_us);
	} else {
		cs_print_append(&pb, "CS capabilities (local, t=%llu us):\n",
		                (unsigned long long)caps->timestamp_us);
	}
	cs_print_append(&pb, "  configs %u, max consecutive procedures %u, antennas %u, max paths %u\n",
	                (unsigned int)caps->num_config_supported,
	                (unsigned int)caps->max_consecutive_procedures_supported,
	                (unsigned int)caps->num_antennas_supported,
	                (unsigned int)caps->max_antenna_paths_supported);
	cs_print_append(&pb, "  roles: initiator %u, reflector %u; mode-3 %u\n",
	                (unsigned int)caps->initiator_supported,
	                (unsigned int)caps->reflector_supported,
	                (unsigned int)caps->mode_3_supported);
	cs_print_append(&pb, "  RTT precision/N: AA-only %u/%u, sounding %u/%u, random %u/%u\n",
	                (unsigned int)caps->rtt_aa_only_precision,
	                (unsigned int)caps->rtt_aa_only_n,
	                (unsigned int)caps->rtt_sounding_precision,
	                (unsigned int)caps->rtt_sounding_n,
	                (unsigned int)caps->rtt_random_payload_precision,
	                (unsigned int)caps->rtt_random_payload_n);
	cs_print_append(&pb, "  NADM: sounding %u, random %u; CS_SYNC 2M %u, 2M 2BT %u\n",
	                (unsigned int)caps->phase_based_nadm_sounding_supported,
	                (unsigned int)caps->phase_based_nadm_random_supported,
	                (unsigned int)caps->cs_sync_2m_phy_supported,
	                (unsigned int)caps->cs_sync_2m_2bt_phy_supported);
	cs_print_append(&pb, "  subfeatures: no-FAE %u, CSA #3c %u, PBR from sounding %u, IPT reflector %u\n",
	                (unsigned int)caps->cs_without_fae_supported,
	                (unsigned int)caps->chsel_alg_3c_supported,
	                (unsigned int)caps->pbr_from_rtt_sounding_seq_supported,
	                (unsigned int)caps->cs_ipt_reflector_supported);
	cs_print_append(&pb, "  timing masks: T_IP1 0x%04x, T_IP2 0x%04x, T_FCS 0x%04x, T_PM 0x%04x\n",
	                (unsigned int)caps->t_ip1_times_supported,
	                (unsigned int)caps->t_ip2_times_supported,
	                (unsigned int)caps->t_fcs_times_supported,
	                (unsigned int)caps->t_pm_times_supported);
	cs_print_append(&pb, "  T_SW %u us, TX SNR mask 0x%02x, T_IP2 IPT 0x%04x, T_SW IPT %u us\n",
	                (unsigned int)caps->t_sw_time,
	                (unsigned int)caps->tx_snr_capability,
	                (unsigned int)caps->t_ip2_ipt_times_supported,
	                (unsigned int)caps->t_sw_ipt_time_supported);
	return cs_print_result(&pb);
}
