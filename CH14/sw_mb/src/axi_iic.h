/* Xilinx AXI IIC (PG090) in dynamic-controller mode, master transmit only.
 *
 * Register offsets and the START/STOP FIFO markers are PG090's; the sequence
 * is the one CH10 proved against this panel from Python, moved into C
 * unchanged so that a failure here is a failure of the port, not of the
 * protocol.
 *
 * Master transmit is all there is because the AiP31068L is write-only -- it
 * has no readable register the display needs. */
#ifndef AXI_IIC_H
#define AXI_IIC_H

#include <stdint.h>
#include <stddef.h>

/* Register offsets from the IP base address. */
#define IIC_ISR      0x020u   /* interrupt status */
#define IIC_SOFTR    0x040u   /* soft reset: write 0x0A */
#define IIC_CR       0x100u   /* control */
#define IIC_SR       0x104u   /* status */
#define IIC_TX_FIFO  0x108u   /* transmit FIFO */

#define IIC_CR_EN            0x01u
#define IIC_CR_TXFIFO_RESET  0x02u

#define IIC_SR_BB            0x04u   /* bus busy */

#define IIC_ISR_TX_ERROR     0x02u   /* INT(1): slave NACK in master transmit */

#define IIC_SOFTR_KEY        0x0Au

/* Dynamic-mode markers, written alongside the byte in the TX FIFO. */
#define IIC_START            0x100u
#define IIC_STOP             0x200u

typedef enum {
    IIC_OK       =  0,
    IIC_ENACK    = -1,   /* the slave did not acknowledge */
    IIC_EBUSY    = -2,   /* the bus never went idle */
    IIC_EINVAL   = -3
} iic_status_t;

typedef struct {
    uintptr_t base;
} axi_iic_t;

void         axi_iic_init(axi_iic_t *iic, uintptr_t base);
void         axi_iic_reset(axi_iic_t *iic);
iic_status_t axi_iic_write(axi_iic_t *iic, uint8_t addr7,
                           const uint8_t *data, size_t len);

#endif /* AXI_IIC_H */
