/* SPDX-License-Identifier: MIT */
/* SoftDevice Controller vendor settings of the initiator. Separate from
 * cs_role_initiator.c so the native tests can replace it.
 */
#include <multithreading_lock.h>
#include <sdc_hci_vs.h>

#include "cs_role_internal.h"

uint8_t cs_role_controller_t_pm_set(uint8_t t_pm_us) {
	/* The controller's HCI layer does not route CS Params Set: call it
	 * directly, as the NCS HCI driver does at init.
	 */
	const sdc_hci_cmd_vs_cs_params_set_t params = {
		.cs_param_type = SDC_HCI_VS_CS_PARAM_TYPE_CS_T_PM_SET,
		.cs_param_data.cs_t_pm_params.cs_t_pm_length_us = t_pm_us,
	};
	uint8_t status;

	(void)MULTITHREADING_LOCK_ACQUIRE();
	status = sdc_hci_cmd_vs_cs_params_set(&params);
	MULTITHREADING_LOCK_RELEASE();
	return status;
}
