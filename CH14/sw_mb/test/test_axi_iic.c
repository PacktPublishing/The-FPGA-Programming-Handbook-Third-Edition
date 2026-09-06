#include "tap.h"
#include "fake_mmio.h"
#include "axi_iic.h"

#define BASE 0x40800000u

/* A bus that is idle and a slave that acknowledges: the case every other
 * test varies from. */
static void bus_healthy(void)
{
    fake_set(BASE, IIC_SR, 0);            /* not busy */
    fake_set(BASE, IIC_ISR, 0);           /* no error latched */
}

/* Find the nth write to a particular register, skipping the others. */
static uint32_t nth_write_to(uint32_t off, int n)
{
    int seen = 0;
    for (size_t i = 0; i < fake.write_count; i++) {
        if (fake.writes[i].off == off) {
            if (seen == n) return fake.writes[i].value;
            seen++;
        }
    }
    return 0xDEADBEEFu;
}

static int count_writes_to(uint32_t off)
{
    int n = 0;
    for (size_t i = 0; i < fake.write_count; i++)
        if (fake.writes[i].off == off) n++;
    return n;
}

TEST(init_resets_the_core_and_enables_it)
{
    axi_iic_t iic;
    fake_reset();
    bus_healthy();

    axi_iic_init(&iic, BASE);

    /* Soft reset first: it is the only thing that clears a bus-busy left
     * over from a transaction the previous bitstream abandoned mid-byte. */
    ASSERT_EQ_INT(nth_write_to(IIC_SOFTR, 0), IIC_SOFTR_KEY);
    ASSERT_EQ_INT(nth_write_to(IIC_CR, 0), IIC_CR_TXFIFO_RESET);
    ASSERT_EQ_INT(nth_write_to(IIC_CR, 1), IIC_CR_EN);
}

TEST(write_frames_the_address_with_a_start_marker)
{
    axi_iic_t iic;
    const uint8_t data[] = { 0x80, 0x01 };
    fake_reset();
    bus_healthy();
    axi_iic_init(&iic, BASE);
    size_t before = fake.write_count;
    (void)before;

    ASSERT_EQ_INT(axi_iic_write(&iic, 0x3E, data, 2), IIC_OK);

    /* Address word is START | (addr << 1), with the read/write bit left at 0
     * for a write. 0x3E << 1 is 0x7C. */
    ASSERT_EQ_INT(nth_write_to(IIC_TX_FIFO, 0), IIC_START | 0x7Cu);
}

TEST(write_marks_only_the_last_byte_with_stop)
{
    /* A STOP on the wrong byte truncates the transfer; a missing STOP leaves
     * the bus held and every later transaction times out on bus-busy. */
    axi_iic_t iic;
    const uint8_t data[] = { 0x80, 0x01, 0x02 };
    fake_reset();
    bus_healthy();
    axi_iic_init(&iic, BASE);

    ASSERT_EQ_INT(axi_iic_write(&iic, 0x3E, data, 3), IIC_OK);

    ASSERT_EQ_INT(count_writes_to(IIC_TX_FIFO), 4);           /* address + 3 */
    ASSERT_EQ_INT(nth_write_to(IIC_TX_FIFO, 1), 0x80u);
    ASSERT_EQ_INT(nth_write_to(IIC_TX_FIFO, 2), 0x01u);
    ASSERT_EQ_INT(nth_write_to(IIC_TX_FIFO, 3), IIC_STOP | 0x02u);
}

TEST(write_of_a_single_byte_carries_start_and_stop)
{
    axi_iic_t iic;
    const uint8_t data[] = { 0x40 };
    fake_reset();
    bus_healthy();
    axi_iic_init(&iic, BASE);

    ASSERT_EQ_INT(axi_iic_write(&iic, 0x3E, data, 1), IIC_OK);
    ASSERT_EQ_INT(count_writes_to(IIC_TX_FIFO), 2);
    ASSERT_EQ_INT(nth_write_to(IIC_TX_FIFO, 1), IIC_STOP | 0x40u);
}

TEST(write_reports_a_slave_that_does_not_acknowledge)
{
    /* A panel that is not plugged in NACKs, and a driver that ignored the
     * interrupt status would return success and display nothing -- the exact
     * symptom that is hardest to tell from a code bug. */
    axi_iic_t iic;
    const uint8_t data[] = { 0x80, 0x01 };
    fake_reset();
    bus_healthy();
    axi_iic_init(&iic, BASE);
    fake_set(BASE, IIC_ISR, IIC_ISR_TX_ERROR);

    ASSERT_EQ_INT(axi_iic_write(&iic, 0x3E, data, 2), IIC_ENACK);
}

TEST(a_nack_leaves_the_core_reset_and_usable)
{
    /* After a NACK the core can be left with a stale error and a half-drained
     * FIFO. The next transaction has to start from a known state, or one
     * unplugged panel poisons every transfer that follows it. */
    axi_iic_t iic;
    const uint8_t data[] = { 0x80, 0x01 };
    fake_reset();
    bus_healthy();
    axi_iic_init(&iic, BASE);
    fake_set(BASE, IIC_ISR, IIC_ISR_TX_ERROR);
    int softr_before = count_writes_to(IIC_SOFTR);

    axi_iic_write(&iic, 0x3E, data, 2);

    ASSERT_EQ_INT(count_writes_to(IIC_SOFTR), softr_before + 1);
}

TEST(write_clears_stale_interrupt_flags_before_starting)
{
    /* Otherwise the error left by the previous transaction is read back as
     * this one's, and a working panel reports a NACK forever. */
    axi_iic_t iic;
    const uint8_t data[] = { 0x80 };
    fake_reset();
    bus_healthy();
    axi_iic_init(&iic, BASE);
    fake_set(BASE, IIC_ISR, IIC_ISR_TX_ERROR);
    fake_reset();
    bus_healthy();
    fake_set(BASE, IIC_ISR, IIC_ISR_TX_ERROR);

    axi_iic_write(&iic, 0x3E, data, 1);

    /* The status register is write-one-to-clear, so clearing it means writing
     * back exactly what was read. */
    ASSERT_EQ_INT(nth_write_to(IIC_ISR, 0), IIC_ISR_TX_ERROR);
}

TEST(write_gives_up_on_a_bus_that_never_goes_idle)
{
    /* A stuck-low SDA -- no pull-up, or a slave mid-transfer when the PL was
     * reprogrammed -- must not hang the application forever. There is no
     * watchdog on this processor and no console to notice a hang on. */
    axi_iic_t iic;
    const uint8_t data[] = { 0x80 };
    fake_reset();
    fake_set(BASE, IIC_SR, IIC_SR_BB);      /* busy, and stays busy */
    fake_set(BASE, IIC_ISR, 0);
    axi_iic_init(&iic, BASE);

    ASSERT_EQ_INT(axi_iic_write(&iic, 0x3E, data, 1), IIC_EBUSY);
}

TEST(write_rejects_a_zero_length_transfer)
{
    /* No bytes means no STOP marker to attach, which would leave the bus
     * held. Refusing is better than emitting an address and walking away. */
    axi_iic_t iic;
    fake_reset();
    bus_healthy();
    axi_iic_init(&iic, BASE);
    int fifo_before = count_writes_to(IIC_TX_FIFO);

    ASSERT_EQ_INT(axi_iic_write(&iic, 0x3E, (const uint8_t *)"", 0), IIC_EINVAL);
    ASSERT_EQ_INT(count_writes_to(IIC_TX_FIFO), fifo_before);
}

TAP_MAIN_BEGIN
    RUN(init_resets_the_core_and_enables_it);
    RUN(write_frames_the_address_with_a_start_marker);
    RUN(write_marks_only_the_last_byte_with_stop);
    RUN(write_of_a_single_byte_carries_start_and_stop);
    RUN(write_reports_a_slave_that_does_not_acknowledge);
    RUN(a_nack_leaves_the_core_reset_and_usable);
    RUN(write_clears_stale_interrupt_flags_before_starting);
    RUN(write_gives_up_on_a_bus_that_never_goes_idle);
    RUN(write_rejects_a_zero_length_transfer);
TAP_MAIN_END
