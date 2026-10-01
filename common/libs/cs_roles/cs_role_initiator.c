/* SPDX-License-Identifier: MIT */
/* CS initiator: RAS requestor discovery and real-time subscription, FAE table,
 * configuration, CS security and procedures (role thread), and the local step
 * buffer and RAS data stream (Bluetooth context). With reflector data none,
 * the RAS parts are skipped and IPT is required instead.
 */
#include <errno.h>
#include <string.h>
#include <bluetooth/gatt_dm.h>
#include <bluetooth/services/ras.h>
#include <zephyr/bluetooth/conn.h>
#include <zephyr/bluetooth/cs.h>
#include <zephyr/kernel.h>
#include <zephyr/net_buf.h>

#include "cs_ras.h"
#include "app_log/app_log.h"
#include "cs_role_internal.h"

APP_LOG_MODULE(cs_roles);

/* Local step data of one procedure, as in the NCS ras_initiator sample: the RAS
 * parser needs it to interpret the peer's steps.
 */
#define LOCAL_PROCEDURE_MEM                                                           \
	((BT_RAS_MAX_STEPS_PER_PROCEDURE * sizeof(struct bt_le_cs_subevent_step)) + \
	 (BT_RAS_MAX_STEPS_PER_PROCEDURE * BT_RAS_MAX_STEP_DATA_LEN))

BUILD_ASSERT(CS_RAS_ABORT_STEP_NONE == CS_SUBEVENT_ABORT_STEP_NONE);

/* Role thread. */

static void post_result(uint8_t type, struct bt_conn *conn, int err) {
	struct cs_role_msg msg = { .type = type, .err = err };

	if (cs_role_is_ours(conn)) {
		msg.conn = bt_conn_ref(conn);
		cs_role_post(&msg);
	}
}

static void discovery_completed(struct bt_gatt_dm *dm, void *context) {
	struct bt_conn *conn = bt_gatt_dm_conn_get(dm);
	int err = bt_ras_rreq_alloc_and_assign_handles(dm, conn);
	int release_err = bt_gatt_dm_data_release(dm);

	ARG_UNUSED(context);
	post_result(CS_ROLE_MSG_RAS_DISCOVERED, conn, err ? err : release_err);
}

static void discovery_not_found(struct bt_conn *conn, void *context) {
	ARG_UNUSED(context);
	post_result(CS_ROLE_MSG_RAS_DISCOVERED, conn, -ENOENT);
}

static void discovery_error(struct bt_conn *conn, int err, void *context) {
	ARG_UNUSED(context);
	post_result(CS_ROLE_MSG_RAS_DISCOVERED, conn, err ? err : -EIO);
}

static const struct bt_gatt_dm_cb discovery_callbacks = {
	.completed = discovery_completed,
	.service_not_found = discovery_not_found,
	.error_found = discovery_error,
};

static void features_cb(struct bt_conn *conn, uint32_t feature_bits, int err) {
	struct cs_role_msg msg = { .type = CS_ROLE_MSG_RAS_FEATURES, .err = err,
	                           .features = feature_bits };

	if (cs_role_is_ours(conn)) {
		msg.conn = bt_conn_ref(conn);
		cs_role_post(&msg);
	}
}

NET_BUF_SIMPLE_DEFINE_STATIC(local_steps, LOCAL_PROCEDURE_MEM);
NET_BUF_SIMPLE_DEFINE_STATIC(peer_steps, BT_RAS_PROCEDURE_MEM);
static void ras_data_cb(struct bt_conn *conn, uint16_t ranging_counter, int err);

/* The reflector's data arrives through RAS; otherwise the initiator runs on IPT alone. */
static bool ras_used(void) {
	return cs_role.initiator.peer_data == CS_CONFIG_PEER_DATA_RAS_REALTIME;
}

/* Issue the next command the setup needs; steps done on this link are skipped. */
void cs_role_initiator_advance(void) {
	struct cs_capabilities local;
	struct bt_conn *conn = cs_role.conn;
	const struct bt_le_cs_procedure_enable_param enable = {
		.config_id = cs_role.initiator.config_id,
		.enable = BT_CONN_LE_CS_PROCEDURES_ENABLED,
	};
	int err;

	if (!cs_role.encrypted) {
		cs_role_set_stage(CS_ROLE_STAGE_WAIT_ENCRYPTION, true);
		return;
	}
	if (ras_used() && !cs_role.rreq_allocated) {
		err = bt_gatt_dm_start(conn, BT_UUID_RANGING_SERVICE, &discovery_callbacks, NULL);
		if (err) {
			cs_role_fail(CS_ROLE_FAILURE_RAS_DISCOVERY, 0U, err);
		} else {
			cs_role_set_stage(CS_ROLE_STAGE_RAS_DISCOVERY, true);
		}
		return;
	}
	if (ras_used() && !cs_role.rreq_subscribed) {
		err = bt_ras_rreq_read_features(conn, features_cb);
		if (err) {
			cs_role_fail(CS_ROLE_FAILURE_RAS_DISCOVERY, 0U, err);
		} else {
			cs_role_set_stage(CS_ROLE_STAGE_RAS_FEATURES, true);
		}
		return;
	}
	if (!cs_role.capabilities_read) {
		err = cs_capabilities_read_local(&local);
		if (!err) {
			cs_role_event_capabilities(&local);
			err = cs_initiator_config_apply_default_settings(&cs_role.initiator, conn);
		}
		if (!err) {
			err = bt_le_cs_read_remote_supported_capabilities(conn);
		}
		if (err) {
			cs_role_fail(CS_ROLE_FAILURE_CAPABILITIES, 0U, err);
		} else {
			cs_role_set_stage(CS_ROLE_STAGE_REMOTE_CAPABILITIES, true);
		}
		return;
	}
	if (!cs_role.config_created) {
		/* Set on every creation: the controller keeps the previous run's value. */
		uint8_t status = cs_role_controller_t_pm_set(cs_role.initiator.t_pm_us);

		if (status) {
			cs_role_fail(CS_ROLE_FAILURE_CONFIG, status, -EIO);
			return;
		}
		err = cs_initiator_config_apply_creation(&cs_role.initiator, conn);
		if (err) {
			cs_role_fail(CS_ROLE_FAILURE_CONFIG, 0U, err);
		} else {
			cs_role_set_stage(CS_ROLE_STAGE_CONFIG, true);
		}
		return;
	}
	if (!cs_role.security_enabled) {
		err = bt_le_cs_security_enable(conn);
		if (err) {
			cs_role_fail(CS_ROLE_FAILURE_SECURITY, 0U, err);
		} else {
			cs_role_set_stage(CS_ROLE_STAGE_SECURITY, true);
		}
		return;
	}
	err = cs_initiator_config_apply_procedure(&cs_role.initiator, conn);
	if (!err) {
		err = bt_le_cs_procedure_enable(conn, &enable);
	}
	if (err) {
		cs_role_fail(CS_ROLE_FAILURE_PROCEDURE, 0U, err);
	} else {
		cs_role_set_stage(CS_ROLE_STAGE_ENABLE, true);
	}
}

static void features_read(const struct cs_role_msg *msg) {
	int err = msg->err;

	if (err) {
		cs_role_fail(CS_ROLE_FAILURE_RAS_DISCOVERY, 0U, err);
		return;
	}
	if (!(msg->features & RAS_FEAT_REALTIME_RD)) {
		cs_role_fail(CS_ROLE_FAILURE_RAS_NO_REALTIME, 0U, -ENOTSUP);
		return;
	}
	err = bt_ras_rreq_realtime_rd_subscribe(cs_role.conn, &peer_steps, ras_data_cb);
	if (err) {
		cs_role_fail(CS_ROLE_FAILURE_RAS_DISCOVERY, 0U, err);
		return;
	}
	cs_role.rreq_subscribed = true;
	cs_role_notify(CS_ROLE_STATE_RAS_READY, CS_ROLE_FAILURE_NONE, CS_ROLE_STOP_NONE, 0U, 0);
	cs_role_initiator_advance();
}

void cs_role_initiator_handle(const struct cs_role_msg *msg) {
	enum cs_role_stage stage = cs_role.stage;
	int err;

	switch (msg->type) {
	case CS_ROLE_MSG_RAS_DISCOVERED:
		/* Track the instance even if the setup was cancelled meanwhile. */
		cs_role.rreq_allocated = cs_role.rreq_allocated || msg->err == 0;
		if (stage == CS_ROLE_STAGE_RAS_DISCOVERY) {
			if (msg->err) {
				cs_role_fail(CS_ROLE_FAILURE_RAS_DISCOVERY, 0U, msg->err);
			} else {
				cs_role_initiator_advance();
			}
		}
		break;
	case CS_ROLE_MSG_RAS_FEATURES:
		if (stage == CS_ROLE_STAGE_RAS_FEATURES) {
			features_read(msg);
		}
		break;
	case CS_ROLE_MSG_REMOTE_CAPABILITIES:
		if (stage != CS_ROLE_STAGE_REMOTE_CAPABILITIES) {
			break;
		}
		if (msg->status) {
			cs_role_fail(CS_ROLE_FAILURE_CAPABILITIES, msg->status, -EIO);
			break;
		}
		if (!ras_used() && !msg->cs.ipt) {
			APP_LOG_ERR("Reflector data none needs IPT, which the peer does not support");
			cs_role_fail(CS_ROLE_FAILURE_PEER_IPT, 0U, -ENOTSUP);
			break;
		}
		if (msg->cs.num_antennas < 4U &&
		    (cs_role.initiator.procedure.preferred_peer_antenna >> msg->cs.num_antennas) != 0U) {
			/* The nRF54L15 Tag's controller switches to such an antenna
			 * unchecked and faults on the missing antenna GPIO.
			 */
			APP_LOG_ERR("Preferred peer antennas 0x%02x, the peer has %u",
			            (unsigned int)cs_role.initiator.procedure.preferred_peer_antenna,
			            (unsigned int)msg->cs.num_antennas);
			cs_role_fail(CS_ROLE_FAILURE_PEER_ANTENNA, 0U, -ERANGE);
			break;
		}
		cs_role.capabilities_read = true;
		if (msg->cs.fae_needed && !cs_role.fae_read) {
			/* Once per link; skipped when the peer supports CS without FAE. */
			err = bt_le_cs_read_remote_fae_table(cs_role.conn);
			if (!err) {
				cs_role_set_stage(CS_ROLE_STAGE_FAE, true);
				break;
			}
			/* A failed call is not a table: log it and go on. */
			APP_LOG_WRN("Remote FAE table read not started: %d", err);
		}
		cs_role_initiator_advance();
		break;
	case CS_ROLE_MSG_FAE:
		cs_role.fae_read = true;
		if (msg->status) {
			APP_LOG_WRN("Remote FAE table read failed: HCI status 0x%02x", msg->status);
		}
		if (stage == CS_ROLE_STAGE_FAE) {
			cs_role_initiator_advance();
		}
		break;
	case CS_ROLE_MSG_CONFIG:
		if (msg->status) {
			if (stage == CS_ROLE_STAGE_CONFIG) {
				cs_role_fail(CS_ROLE_FAILURE_CONFIG, msg->status, -EIO);
			}
			break;
		}
		if (msg->cs.config_id == cs_role.initiator.config_id) {
			if (!ras_used() && !msg->cs.ipt) {
				/* The controller negotiated IPT away. No fallback to RAS: the
				 * procedure interval may be too short for its traffic.
				 */
				if (stage == CS_ROLE_STAGE_CONFIG) {
					APP_LOG_ERR("Reflector data none needs IPT, which the configuration does not enable");
					cs_role_fail(CS_ROLE_FAILURE_PEER_IPT, 0U, -ENOTSUP);
				}
				break;
			}
			cs_role.config_created = true;
			if (stage == CS_ROLE_STAGE_CONFIG) {
				cs_role_initiator_advance();
			}
		} else {
			APP_LOG_WRN("CS configuration %u ignored: configured ID is %u",
			            (unsigned int)msg->cs.config_id,
			            (unsigned int)cs_role.initiator.config_id);
		}
		break;
	case CS_ROLE_MSG_CS_SECURITY:
		if (msg->status) {
			if (stage == CS_ROLE_STAGE_SECURITY) {
				cs_role_fail(CS_ROLE_FAILURE_SECURITY, msg->status, -EACCES);
			}
			break;
		}
		cs_role.security_enabled = true;
		if (stage == CS_ROLE_STAGE_SECURITY) {
			cs_role_initiator_advance();
		}
		break;
	case CS_ROLE_MSG_RAS_RESOLVED:
		if (stage == CS_ROLE_STAGE_STOP_RAS &&
		    !(atomic_get(&cs_role_data.ras_pending) & CS_ROLE_RAS_PENDING)) {
			cs_role_stop_finish(0);
		}
		break;
	default:
		break;
	}
}

void cs_role_initiator_release(bool link_down) {
	if (cs_role.rreq_subscribed && !link_down) {
		(void)bt_ras_rreq_realtime_rd_unsubscribe(cs_role.conn);
	}
	if (cs_role.rreq_allocated && cs_role.conn) {
		/* After a disconnection the RAS module has freed it already; this is a no-op. */
		bt_ras_rreq_free(cs_role.conn);
	}
	cs_role.rreq_subscribed = false;
	cs_role.rreq_allocated = false;
	atomic_clear(&cs_role_data.ras_pending);
}

/* Procedures are disabled: wait for the reflector's data of the last procedure. */
void cs_role_initiator_disabled(void) {
	if (!ras_used()) {
		cs_role_stop_finish(0);
		return;
	}
	atomic_set(&cs_role_data.ras_waiter, 1);
	if (!(atomic_get(&cs_role_data.ras_pending) & CS_ROLE_RAS_PENDING)) {
		cs_role_stop_finish(0);
		return;
	}
	cs_role_set_stage(CS_ROLE_STAGE_STOP_RAS, true);
}

void cs_role_initiator_stop_ras_timeout(void) {
	atomic_val_t pending = atomic_get(&cs_role_data.ras_pending);

	if ((pending & CS_ROLE_RAS_PENDING) &&
	    atomic_cas(&cs_role_data.ras_pending, pending,
	               CS_ROLE_RAS_CLAIMED | (uint16_t)pending)) {
		/* Claimed, so late data for it is discarded, never streamed after STOP. */
		cs_role_event_ras_lost((uint16_t)pending, -ETIMEDOUT);
		cs_role_stop_finish(cs_role.stop_reason == CS_ROLE_STOP_HOST ? -ETIMEDOUT : 0);
		return;
	}
	cs_role_stop_finish(0);
}

/* Bluetooth context. */

static struct cs_ras_tracker tracker;
/* Local steps of the buffered procedure did not all fit. */
static bool local_overflow;

void cs_role_initiator_data_reset(void) {
	cs_ras_tracker_reset(&tracker);
	net_buf_simple_reset(&local_steps);
	net_buf_simple_reset(&peer_steps);
	local_overflow = false;
	atomic_clear(&cs_role_data.ras_pending);
}

static void resolved(void) {
	struct cs_role_msg msg = { .type = CS_ROLE_MSG_RAS_RESOLVED };

	if (atomic_get(&cs_role_data.ras_waiter)) {
		cs_role_post(&msg);
	}
}

/* Resolve @p procedure_counter's pending marker. False: the role thread claimed
 * it and has reported it lost already.
 */
static bool resolve(uint16_t procedure_counter) {
	atomic_val_t pending = CS_ROLE_RAS_PENDING | procedure_counter;
	atomic_val_t claimed = CS_ROLE_RAS_CLAIMED | procedure_counter;

	if (atomic_cas(&cs_role_data.ras_pending, pending, 0)) {
		resolved();
		return true;
	}
	return !atomic_cas(&cs_role_data.ras_pending, claimed, 0);
}

/* Report @p procedure_counter lost unless the role thread already did. */
static void procedure_lost(uint16_t procedure_counter, int error) {
	if (resolve(procedure_counter)) {
		cs_role_event_ras_lost(procedure_counter, error);
	}
}

void cs_role_initiator_local_subevent(const struct bt_conn_le_cs_subevent_result *result) {
	uint16_t counter = result->header.procedure_counter;
	bool done = result->header.procedure_done_status != BT_CONN_LE_CS_PROCEDURE_INCOMPLETE;
	struct cs_ras_local_action action;

	if (!result->step_data_buf ||
	    result->header.subevent_done_status == BT_CONN_LE_CS_SUBEVENT_ABORTED) {
		/* No steps to buffer; the procedure may still end here. */
		if (done && tracker.buffered && tracker.procedure_counter == counter) {
			atomic_set(&cs_role_data.ras_pending, CS_ROLE_RAS_PENDING | counter);
		}
		return;
	}
	action = cs_ras_local_subevent(&tracker, counter, done);
	if (action.lost) {
		procedure_lost(action.lost_procedure_counter, -ENOBUFS);
	}
	if (action.reset) {
		net_buf_simple_reset(&local_steps);
		local_overflow = false;
	}
	if (result->step_data_buf->len <= net_buf_simple_tailroom(&local_steps)) {
		net_buf_simple_add_mem(&local_steps, result->step_data_buf->data,
		                       result->step_data_buf->len);
	} else {
		local_overflow = true;
	}
	if (done) {
		atomic_set(&cs_role_data.ras_pending, CS_ROLE_RAS_PENDING | counter);
	}
}

/* Pass 1 records what each subevent will stream; pass 2 streams it. */
struct ras_subevent_plan {
	uint16_t size;
	uint16_t num_tones;
	uint8_t num_steps;
	uint8_t reported;
	bool invalid;
};

static struct ras_subevent_plan plan[CONFIG_APP_CS_ROLES_RAS_MAX_SUBEVENTS];

struct ras_stream {
	bool pass_2;
	uint16_t procedure_counter;
	uint8_t config_id;
	uint8_t antenna_paths_mask;
	uint8_t paths;
	struct cs_subevent_parse_cfg cfg;
	/* Index of the current subevent; -1 before the first. */
	int index;
	int planned;
	bool truncated;
	bool open;
	uint8_t emitted;
};

static bool ras_ranging_header(struct ras_ranging_header *header, void *user_data) {
	struct ras_stream *ctx = user_data;
	uint8_t id = header->config_id;

	ctx->config_id = id;
	ctx->antenna_paths_mask = header->antenna_paths_mask;
	ctx->paths = cs_ras_antenna_paths(header->antenna_paths_mask);
	/* An empty mask is valid: the reflector's controller reports no antenna
	 * paths without phase measurement (mode 1 only).
	 */
	if (id > CS_CONFIG_ID_MAX || !(atomic_get(&cs_role_data.layouts) & BIT(id)) ||
	    ctx->paths > CS_STEP_MAX_ANTENNA_PATHS) {
		return false;
	}
	ctx->cfg = (struct cs_subevent_parse_cfg){
		.role = BT_CONN_LE_CS_ROLE_REFLECTOR,
		.rtt_type = (enum bt_conn_le_cs_rtt_type)cs_role_data.rtt_types[id],
	};
	return true;
}

static void close_subevent(struct ras_stream *ctx) {
	if (ctx->open) {
		const struct ras_subevent_plan *p = &plan[ctx->index];

		cs_role_stream_end(p->num_steps == p->reported);
		ctx->open = false;
	}
}

static bool ras_subevent_header(struct ras_subevent_header *header, void *user_data) {
	struct ras_stream *ctx = user_data;

	if (!ctx->pass_2) {
		if (++ctx->index >= (int)ARRAY_SIZE(plan)) {
			ctx->truncated = true;
			return false;
		}
		plan[ctx->index] = (struct ras_subevent_plan){
			.size = sizeof(struct cs_subevent),
			.reported = header->num_steps_reported,
		};
		ctx->planned = ctx->index + 1;
		return true;
	}

	close_subevent(ctx);
	if (++ctx->index >= ctx->planned) {
		return false;
	}
	const struct ras_subevent_plan *p = &plan[ctx->index];
	const struct cs_ras_subevent_fields fields = {
		.start_acl_conn_event = header->start_acl_conn_event,
		.freq_compensation = header->freq_compensation,
		.ranging_done_status = header->ranging_done_status,
		.subevent_done_status = header->subevent_done_status,
		.ranging_abort_reason = header->ranging_abort_reason,
		.subevent_abort_reason = header->subevent_abort_reason,
		.ref_power_level = header->ref_power_level,
		.num_steps_reported = header->num_steps_reported,
	};
	struct cs_ras_subevent_header mapped;
	struct cs_subevent out;

	(void)cs_ras_map_subevent(ctx->config_id, ctx->antenna_paths_mask, ctx->procedure_counter,
	                          (uint16_t)ctx->index, &fields, &mapped);
	out = (struct cs_subevent){
		.size = p->size,
		.num_steps = p->num_steps,
		.config_id = mapped.config_id,
		.role = BT_CONN_LE_CS_ROLE_REFLECTOR,
		.rtt_type = (uint8_t)ctx->cfg.rtt_type,
		.num_antenna_paths = mapped.num_antenna_paths,
		.reference_power_level = mapped.reference_power_level,
		.subevent_id = mapped.subevent_id,
		.event_id = mapped.event_id,
		.procedure_id = mapped.procedure_id,
		.frequency_compensation = mapped.frequency_compensation,
		.procedure_done_status = mapped.procedure_done_status,
		.subevent_done_status = mapped.subevent_done_status,
		.procedure_abort_reason = mapped.procedure_abort_reason,
		.subevent_abort_reason = mapped.subevent_abort_reason,
		.abort_step = mapped.abort_step,
		.timestamp_us = cs_subevent_timestamp_us(),
	};
	(void)cs_role_stream_begin(&out, p->num_tones);
	ctx->open = true;
	ctx->emitted = 0U;
	return true;
}

static bool ras_step(struct bt_le_cs_subevent_step *local_step,
                     struct bt_le_cs_subevent_step *peer_step, void *user_data) {
	struct ras_stream *ctx = user_data;
	struct ras_subevent_plan *p;

	ARG_UNUSED(local_step);
	if (ctx->index < 0 || ctx->index >= ctx->planned) {
		return false;
	}
	p = &plan[ctx->index];
	if (!ctx->pass_2) {
		int size = p->invalid ? -EINVAL :
		           cs_step_decode(peer_step, &ctx->cfg, ctx->paths, p->num_steps, NULL, 0U);

		/* Only the steps before the first undecodable one are streamed. */
		if (size < 0 || p->num_steps == UINT8_MAX) {
			p->invalid = true;
		} else {
			p->size += (uint16_t)size;
			p->num_tones += cs_step_num_tones(peer_step->mode, ctx->paths);
			p->num_steps++;
		}
		return true;
	}
	if (ctx->open && ctx->emitted < p->num_steps) {
		uint8_t record[CS_STEP_MAX_SIZE];

		(void)cs_step_decode(peer_step, &ctx->cfg, ctx->paths, ctx->emitted, record,
		                     sizeof(record));
		cs_role_stream_step((const struct cs_step_header *)record);
	}
	ctx->emitted++;
	return true;
}

/* Stream the reflector's subevents of one procedure. */
static int stream_procedure(uint16_t procedure_counter) {
	struct net_buf_simple_state peer_state;
	struct net_buf_simple_state local_state;
	struct ras_stream ctx = { .procedure_counter = procedure_counter, .index = -1 };
	bool incomplete;

	net_buf_simple_save(&peer_steps, &peer_state);
	net_buf_simple_save(&local_steps, &local_state);
	bt_ras_rreq_rd_subevent_data_parse(&peer_steps, &local_steps, BT_CONN_LE_CS_ROLE_INITIATOR,
	                                   ras_ranging_header, ras_subevent_header, ras_step, &ctx);
	/* The parser returns nothing; data left over means it stopped early. */
	incomplete = peer_steps.len != 0U;
	if (ctx.planned == 0) {
		return -EBADMSG;
	}
	for (int i = 0; i < ctx.planned; i++) {
		incomplete = incomplete || plan[i].num_steps != plan[i].reported;
	}

	net_buf_simple_restore(&peer_steps, &peer_state);
	net_buf_simple_restore(&local_steps, &local_state);
	ctx.pass_2 = true;
	ctx.index = -1;
	bt_ras_rreq_rd_subevent_data_parse(&peer_steps, &local_steps, BT_CONN_LE_CS_ROLE_INITIATOR,
	                                   ras_ranging_header, ras_subevent_header, ras_step, &ctx);
	close_subevent(&ctx);
	if (ctx.truncated) {
		return -ENOMEM;
	}
	return incomplete ? -EBADMSG : 0;
}

static void ras_data_cb(struct bt_conn *conn, uint16_t ranging_counter, int err) {
	uint16_t procedure_counter;
	int match;

	if (!cs_role_is_ours(conn)) {
		return;
	}
	match = cs_ras_match(&tracker, ranging_counter, &procedure_counter);
	if (match != 0) {
		/* No local procedure to pair with: nothing can be streamed. Late data
		 * of a procedure already reported lost is not reported again.
		 */
		if (match != -EALREADY) {
			cs_role_event_ras_lost(ranging_counter, err ? err : -ENOENT);
		}
		net_buf_simple_reset(&peer_steps);
		return;
	}
	if (!resolve(procedure_counter)) {
		/* STOP gave up on it and reported it lost; do not stream it after STOP. */
		goto out;
	}
	if (err || local_overflow) {
		cs_role_event_ras_lost(procedure_counter, err ? err : -ENOMEM);
	} else {
		err = stream_procedure(procedure_counter);
		if (err) {
			cs_role_event_ras_lost(procedure_counter, err);
		}
	}
out:
	net_buf_simple_reset(&peer_steps);
	net_buf_simple_reset(&local_steps);
	local_overflow = false;
}
