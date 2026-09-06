/* Integer formatting, because there is no printf here worth its size and no
 * FPU to make a float one meaningful anyway.
 *
 * Everything the display shows is a scaled integer: millidegrees, microvolts.
 * fmt_fixed renders one of those with however many decimal places fit in the
 * column, rounding rather than truncating -- 0.8509 V shown to three places
 * is 0.851, and a display that said 0.850 would be wrong by a whole count in
 * the digit a reader is watching. */
#ifndef FMT_H
#define FMT_H

#include <stddef.h>
#include <stdint.h>

/* Render `value`, which carries `value_decimals` implied decimal places, with
 * `show_decimals` of them. Returns the length written, or -1 if it would not
 * fit in `cap` including the terminator, in which case out[0] is set to 0.
 *
 *   fmt_fixed(b, 8,  42345, 3, 1)  ->  "42.3"
 *   fmt_fixed(b, 8, 851000, 6, 3)  ->  "0.851"
 *   fmt_fixed(b, 8,  -1500, 3, 1)  ->  "-1.5"
 */
int fmt_fixed(char *out, size_t cap, int32_t value,
              unsigned value_decimals, unsigned show_decimals);

/* Copy `src` into a field of exactly `width` characters, padding with spaces.
 * A 16x2 panel has no concept of clearing to end of line, so anything shorter
 * than the field leaves the previous frame's characters behind. Returns -1 if
 * the field plus terminator does not fit in `cap`. */
int fmt_pad(char *out, size_t cap, const char *src, size_t width);

/* Right-align `src` in a field of `width`. Used so a voltage's decimal point
 * does not walk left and right as the integer part changes width. */
int fmt_pad_left(char *out, size_t cap, const char *src, size_t width);

#endif /* FMT_H */
