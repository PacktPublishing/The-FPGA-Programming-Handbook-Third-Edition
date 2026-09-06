#include "axi_iic.h"
#include "mmio.h"

/* How long to wait for the bus to go idle. At 100 kHz the longest transfer
 * this driver produces -- an address and three bytes -- is about 360 us, so
 * 200 ms is three orders of magnitude of headroom and still bounded.
 *
 * It is bounded because it has to be. There is no watchdog on this processor
 * and no console: an unbounded wait on a stuck-low SDA is a hang with no
 * symptom other than a panel that stopped updating. */
#define IIC_IDLE_TIMEOUT_US 200000u
#define IIC_POLL_STEP_US    100u

void axi_iic_reset(axi_iic_t *iic)
{
    /* The soft reset first: it is the only thing that clears a bus-busy left
     * behind by a transaction the previous bitstream abandoned mid-byte. */
    mmio_write32(iic->base, IIC_SOFTR, IIC_SOFTR_KEY);
    plat_delay_us(1000);
    mmio_write32(iic->base, IIC_CR, IIC_CR_TXFIFO_RESET);
    mmio_write32(iic->base, IIC_CR, IIC_CR_EN);
}

void axi_iic_init(axi_iic_t *iic, uintptr_t base)
{
    iic->base = base;
    axi_iic_reset(iic);
}

static iic_status_t wait_bus_idle(axi_iic_t *iic)
{
    uint32_t waited = 0;
    while (mmio_read32(iic->base, IIC_SR) & IIC_SR_BB) {
        if (waited >= IIC_IDLE_TIMEOUT_US)
            return IIC_EBUSY;
        plat_delay_us(IIC_POLL_STEP_US);
        waited += IIC_POLL_STEP_US;
    }
    return IIC_OK;
}

iic_status_t axi_iic_write(axi_iic_t *iic, uint8_t addr7,
                           const uint8_t *data, size_t len)
{
    /* Zero bytes would leave no byte to hang the STOP marker on, and the bus
     * would stay held after the address. */
    if (data == NULL || len == 0)
        return IIC_EINVAL;

    iic_status_t status = wait_bus_idle(iic);
    if (status != IIC_OK)
        return status;

    /* Clear whatever the last transaction latched. The status register is
     * write-one-to-clear, so writing back what was read clears exactly the
     * set bits. Skipping this makes one NACK look permanent: the flag from a
     * panel that was unplugged an hour ago is still there to be read. */
    mmio_write32(iic->base, IIC_ISR, mmio_read32(iic->base, IIC_ISR));

    /* Dynamic controller: the first FIFO word carries the START marker and
     * the addressing byte, whose bottom bit is the read/write flag -- 0 here,
     * because this is a transmit-only driver. */
    mmio_write32(iic->base, IIC_TX_FIFO,
                 IIC_START | ((uint32_t)addr7 << 1));

    for (size_t i = 0; i < len; i++) {
        uint32_t word = data[i];
        if (i == len - 1)
            word |= IIC_STOP;
        mmio_write32(iic->base, IIC_TX_FIFO, word);
    }

    /* Bus-busy takes a moment to assert after the FIFO is loaded. Checking
     * for idle immediately would find the bus idle because the transfer had
     * not started yet, and every transaction would appear to succeed
     * instantly whether or not anything was on the other end. */
    plat_delay_us(1000);
    status = wait_bus_idle(iic);
    if (status != IIC_OK)
        return status;

    if (mmio_read32(iic->base, IIC_ISR) & IIC_ISR_TX_ERROR) {
        /* A NACK can leave a partly drained FIFO and a latched error. Reset
         * so the next transfer starts from a known state rather than
         * inheriting this one's wreckage. */
        axi_iic_reset(iic);
        return IIC_ENACK;
    }
    return IIC_OK;
}
