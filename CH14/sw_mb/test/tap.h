/* A test harness small enough to read in one sitting.
 *
 * No framework, because adding a dependency to unit-test four register-level
 * drivers would be a worse trade than thirty lines of macro. Each test is a
 * function; each failure prints the file, line, expected and actual, and the
 * run keeps going so one broken assumption does not hide the next five. */
#ifndef TAP_H
#define TAP_H

#include <stdio.h>
#include <string.h>
#include <inttypes.h>

extern int tap_fail_count;
extern int tap_test_count;
extern const char *tap_current;

#define TEST(name) static void name(void)

#define RUN(name)                                                            \
    do {                                                                     \
        tap_current = #name;                                                 \
        tap_test_count++;                                                    \
        int before = tap_fail_count;                                         \
        name();                                                              \
        printf("%s %s\n", tap_fail_count == before ? "  ok  " : "  FAIL", #name); \
    } while (0)

#define TAP_FAILED(fmt, ...)                                                 \
    do {                                                                     \
        tap_fail_count++;                                                    \
        printf("  FAIL %s\n    %s:%d: " fmt "\n",                            \
               tap_current, __FILE__, __LINE__, __VA_ARGS__);                \
    } while (0)

#define ASSERT_EQ_INT(actual, expect)                                        \
    do {                                                                     \
        long long a_ = (long long)(actual), e_ = (long long)(expect);        \
        if (a_ != e_)                                                        \
            TAP_FAILED("expected %lld, got %lld", e_, a_);                   \
    } while (0)

/* For conversions, where the last unit is a rounding decision rather than a
 * requirement. The tolerance is always stated at the call site. */
#define ASSERT_NEAR_INT(actual, expect, tol)                                 \
    do {                                                                     \
        long long a_ = (long long)(actual), e_ = (long long)(expect);        \
        long long d_ = a_ > e_ ? a_ - e_ : e_ - a_;                          \
        if (d_ > (long long)(tol))                                           \
            TAP_FAILED("expected %lld +/- %lld, got %lld", e_,               \
                       (long long)(tol), a_);                                \
    } while (0)

#define ASSERT_STR_EQ(actual, expect)                                        \
    do {                                                                     \
        const char *a_ = (actual), *e_ = (expect);                           \
        if (strcmp(a_, e_) != 0)                                             \
            TAP_FAILED("expected \"%s\", got \"%s\"", e_, a_);               \
    } while (0)

#define ASSERT_TRUE(cond)                                                    \
    do {                                                                     \
        if (!(cond)) TAP_FAILED("expected true: %s", #cond);                 \
    } while (0)

#define TAP_MAIN_BEGIN                                                       \
    int tap_fail_count = 0;                                                  \
    int tap_test_count = 0;                                                  \
    const char *tap_current = "";                                            \
    int main(void) {

#define TAP_MAIN_END                                                         \
        printf("\n%d tests, %d failures\n", tap_test_count, tap_fail_count); \
        return tap_fail_count != 0;                                          \
    }

#endif /* TAP_H */
