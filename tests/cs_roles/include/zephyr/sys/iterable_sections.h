/* SPDX-License-Identifier: MIT */
/* The real header, with iterable sections as plain definitions: Mach-O and the
 * host linker do not take Zephyr's section names, and the tests need no iteration.
 */
#ifndef TEST_CS_ROLES_ITERABLE_SECTIONS_H_
#define TEST_CS_ROLES_ITERABLE_SECTIONS_H_

#include_next <zephyr/sys/iterable_sections.h>

#undef STRUCT_SECTION_ITERABLE_ALTERNATE
#define STRUCT_SECTION_ITERABLE_ALTERNATE(secname, struct_type, varname) \
	__attribute__((__used__)) struct struct_type varname

#endif /* TEST_CS_ROLES_ITERABLE_SECTIONS_H_ */
