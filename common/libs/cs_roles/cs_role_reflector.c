/* SPDX-License-Identifier: MIT */
/* CS reflector: RAS responder instance, default settings and remote
 * capabilities at START; the initiator's configuration and procedures follow.
 * Same order as tests/cs_reflector_tag.
 */
#include <errno.h>
#include <bluetooth/services/ras.h>
#include <zephyr/bluetooth/conn.h>
#include <zephyr/bluetooth/cs.h>
#include <zephyr/kernel.h>

#include "cs_role_internal.h"

/* The initiator's configuration is known: store its ID and apply the procedure parameters. */
static int apply_peer_config(void) {
	int err = cs_reflector_config_set_config_id(&cs_role.reflector, cs_role.peer_config_id);

	if (err) {
		return err;
	}
	return cs_reflector_config_apply_procedure(&cs_role.reflector, cs_role.conn);
}

static void wait_for_initiator(void) {
	cs_role_notify(CS_ROLE_STATE_RAS_READY, CS_ROLE_FAILURE_NONE, CS_ROLE_STOP_NONE, 0U, 0);
	/* No deadline: the initiator may be started much later. */
	cs_role_set_stage(cs_role.peer_config ? CS_ROLE_STAGE_ENABLE : CS_ROLE_STAGE_WAIT_PEER_CONFIG,
	                  false);
}

void cs_role_reflector_advance(void) {
	struct cs_capabilities local;
	int err;

	if (!cs_role.encrypted) {
		cs_role_set_stage(CS_ROLE_STAGE_WAIT_ENCRYPTION, true);
		return;
	}
	if (!cs_role.rrsp_allocated) {
		err = bt_ras_rrsp_alloc(cs_role.conn);
		if (err == -EALREADY) {
			/* Allocated automatically (CONFIG_BT_RAS_RRSP_AUTO_ALLOC_INSTANCE). */
			err = 0;
		} else if (!err) {
			cs_role.rrsp_allocated = true;
		}
		if (err) {
			cs_role_fail(CS_ROLE_FAILURE_RAS_DISCOVERY, 0U, err);
			return;
		}
	}
	if (!cs_role.capabilities_read) {
		err = cs_capabilities_read_local(&local);
		if (!err) {
			cs_role_event_capabilities(&local);
			err = cs_reflector_config_apply_default_settings(&cs_role.reflector, cs_role.conn);
		}
		if (!err) {
			err = bt_le_cs_read_remote_supported_capabilities(cs_role.conn);
		}
		if (err) {
			cs_role_fail(CS_ROLE_FAILURE_CAPABILITIES, 0U, err);
		} else {
			cs_role_set_stage(CS_ROLE_STAGE_REMOTE_CAPABILITIES, true);
		}
		return;
	}
	if (cs_role.peer_config) {
		err = apply_peer_config();
		if (err) {
			cs_role_fail(CS_ROLE_FAILURE_CONFIG, 0U, err);
			return;
		}
	}
	wait_for_initiator();
}

void cs_role_reflector_handle(const struct cs_role_msg *msg) {
	int err;

	switch (msg->type) {
	case CS_ROLE_MSG_REMOTE_CAPABILITIES:
		if (cs_role.stage != CS_ROLE_STAGE_REMOTE_CAPABILITIES) {
			break;
		}
		if (msg->status) {
			cs_role_fail(CS_ROLE_FAILURE_CAPABILITIES, msg->status, -EIO);
			break;
		}
		cs_role.capabilities_read = true;
		cs_role_reflector_advance();
		break;
	case CS_ROLE_MSG_CONFIG:
		if (msg->status) {
			if (cs_role.stage == CS_ROLE_STAGE_WAIT_PEER_CONFIG) {
				cs_role_fail(CS_ROLE_FAILURE_CONFIG, msg->status, -EIO);
			}
			break;
		}
		cs_role.peer_config = true;
		cs_role.peer_config_id = msg->cs.config_id;
		if (cs_role.role != CS_ROLE_KIND_REFLECTOR ||
		    (cs_role.stage != CS_ROLE_STAGE_WAIT_PEER_CONFIG &&
		     cs_role.stage != CS_ROLE_STAGE_ENABLE)) {
			/* Applied at START. */
			break;
		}
		err = apply_peer_config();
		if (err) {
			cs_role_fail(CS_ROLE_FAILURE_CONFIG, 0U, err);
			break;
		}
		cs_role_set_stage(CS_ROLE_STAGE_ENABLE, false);
		break;
	case CS_ROLE_MSG_CS_SECURITY:
		/* Started by the initiator; only a failure matters here. */
		if (msg->status && cs_role.stage != CS_ROLE_STAGE_IDLE) {
			cs_role_fail(CS_ROLE_FAILURE_SECURITY, msg->status, -EACCES);
		}
		break;
	default:
		break;
	}
}

void cs_role_reflector_release(bool link_down) {
	ARG_UNUSED(link_down);
	if (cs_role.rrsp_allocated && cs_role.conn) {
		bt_ras_rrsp_free(cs_role.conn);
	}
	/* The initiator's configuration stays valid until the link goes down. */
	cs_role.rrsp_allocated = false;
}
