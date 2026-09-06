/* The fake register space the driver tests run against.
 *
 * MMIO and the delay loop are the only things these drivers touch that is not
 * their own code, so they are the only things faked -- the drivers themselves
 * are exercised as-is, compiled from the same sources the board runs.
 *
 * Reads are answered from a sparse table the test fills in; writes are
 * appended to a log the test asserts against. A read of an address the test
 * never set up is a test bug and is reported as one rather than quietly
 * returning zero, because "returns zero" is exactly the failure mode the
 * SYSMON driver exists to distinguish. */
#ifndef FAKE_MMIO_H
#define FAKE_MMIO_H

#include <stdint.h>
#include <stddef.h>

#define FAKE_MAX_ENTRIES 512

typedef struct {
    uintptr_t base;
    uint32_t  off;
    uint32_t  value;
} fake_access_t;

typedef struct {
    fake_access_t reads[FAKE_MAX_ENTRIES];   /* what a read at base+off answers */
    size_t        read_count;
    fake_access_t writes[FAKE_MAX_ENTRIES];  /* every write, in order */
    size_t        write_count;
    uint32_t      delay_total_us;
    uint32_t      delays[FAKE_MAX_ENTRIES];
    size_t        delay_count;
    int           unmapped_reads;            /* reads the test never set up */
} fake_mmio_t;

extern fake_mmio_t fake;

void     fake_reset(void);
void     fake_set(uintptr_t base, uint32_t off, uint32_t value);
uint32_t fake_written(size_t index);          /* value of the nth write */
uint32_t fake_written_off(size_t index);      /* offset of the nth write */

#endif /* FAKE_MMIO_H */
