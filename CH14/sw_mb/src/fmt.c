#include "fmt.h"

#include <string.h>

/* 10^n for the range of decimal places anything here uses. A table rather
 * than a loop because both are the same size and this one cannot be wrong. */
static const uint32_t pow10_table[] = {
    1u, 10u, 100u, 1000u, 10000u, 100000u, 1000000u, 10000000u
};
#define POW10_MAX ((unsigned)(sizeof pow10_table / sizeof pow10_table[0] - 1))

int fmt_fixed(char *out, size_t cap, int32_t value,
              unsigned value_decimals, unsigned show_decimals)
{
    char digits[16];
    size_t len = 0;
    int negative = value < 0;

    if (out == NULL || cap == 0)
        return -1;
    out[0] = '\0';
    if (value_decimals > POW10_MAX || show_decimals > value_decimals)
        return -1;

    /* Negate in the unsigned domain. INT32_MIN has no positive counterpart,
     * so negating it as a signed int is undefined -- and this runs with no
     * console to notice it on. */
    uint32_t magnitude = negative
        ? (uint32_t)(-(int64_t)value)
        : (uint32_t)value;

    /* Drop the places that are not shown, rounding half away from zero. The
     * carry this can produce is why the integer part is not split off first:
     * 41.96 to one place is 42.0, and rounding the fraction alone would give
     * 41.10. */
    unsigned drop = value_decimals - show_decimals;
    if (drop > 0) {
        uint32_t scale = pow10_table[drop];
        magnitude = (magnitude + scale / 2u) / scale;
    }

    uint32_t scale = pow10_table[show_decimals];
    uint32_t whole = magnitude / scale;
    uint32_t frac = magnitude % scale;

    /* Built backwards, which is the natural direction for base conversion,
     * then reversed once at the end. */
    if (show_decimals > 0) {
        for (unsigned i = 0; i < show_decimals; i++) {
            digits[len++] = (char)('0' + (frac % 10u));
            frac /= 10u;
        }
        digits[len++] = '.';
    }
    do {
        digits[len++] = (char)('0' + (whole % 10u));
        whole /= 10u;
    } while (whole > 0);

    /* The sign survives an integer part of zero: -0.5 must not print as 0.5. */
    if (negative)
        digits[len++] = '-';

    if (len + 1 > cap)
        return -1;

    for (size_t i = 0; i < len; i++)
        out[i] = digits[len - 1 - i];
    out[len] = '\0';
    return (int)len;
}

int fmt_pad(char *out, size_t cap, const char *src, size_t width)
{
    if (out == NULL || cap == 0)
        return -1;
    out[0] = '\0';
    if (width + 1 > cap)
        return -1;

    size_t n = strlen(src);
    if (n > width)
        n = width;                      /* truncate rather than overrun */
    memcpy(out, src, n);
    memset(out + n, ' ', width - n);
    out[width] = '\0';
    return (int)width;
}

int fmt_pad_left(char *out, size_t cap, const char *src, size_t width)
{
    if (out == NULL || cap == 0)
        return -1;
    out[0] = '\0';
    if (width + 1 > cap)
        return -1;

    size_t n = strlen(src);
    if (n >= width) {
        /* Too long to right-align: keep the LEAST significant end, because a
         * voltage that has overflowed its field is more useful with its low
         * digits than with its high ones cut off mid-number. */
        memcpy(out, src + (n - width), width);
    } else {
        memset(out, ' ', width - n);
        memcpy(out + (width - n), src, n);
    }
    out[width] = '\0';
    return (int)width;
}
