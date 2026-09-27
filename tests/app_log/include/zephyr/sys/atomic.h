/* SPDX-License-Identifier: MIT */
/* Test-only atomics: the native test runs on one thread. */
#ifndef TEST_ATOMIC_H_
#define TEST_ATOMIC_H_

typedef long atomic_t;
typedef long atomic_val_t;

static inline atomic_val_t atomic_inc(atomic_t *target) { return (*target)++; }
static inline atomic_val_t atomic_get(const atomic_t *target) { return *target; }
static inline atomic_val_t atomic_clear(atomic_t *target) {
	atomic_val_t old = *target;

	*target = 0;
	return old;
}

#endif /* TEST_ATOMIC_H_ */
