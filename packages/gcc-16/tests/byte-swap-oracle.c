#include <limits.h>
#include <stdio.h>

_Static_assert(UINT_MAX == 0xffffffffu, "this fixture requires 32-bit unsigned int");
unsigned int bswap8(unsigned int value);
void foo(int value);
static unsigned int captured;

void ext(int value) {
    captured = (unsigned int)value;
}

static int check(unsigned int input) {
    /* Derive each output byte using arithmetic, independently of shifts/OR. */
    unsigned int expected = input / 65536u * 65536u
        + input / 256u % 256u + input % 256u * 256u;
#ifdef WRONG_ORACLE
    expected ^= 1u;
#endif
    unsigned int actual = bswap8(input);
    foo((int)input);
    if (actual != expected || captured != expected) {
        fprintf(stderr, "input=%08x bswap=%08x call=%08x expected=%08x\n",
            input, actual, captured, expected);
        return 1;
    }
    return 0;
}

int main(void) {
    /* Exhaust both swapped bytes while varying preserved/sign bits. */
    const unsigned int high_words[] = {0u, 0xffff0000u, 0x12340000u, 0x80000000u};
    for (unsigned int high = 0; high != 4; ++high)
        for (unsigned int low = 0; low != 65536u; ++low)
            if (check(high_words[high] + low))
                return 1;

    unsigned int input = 0x31415926u;
    for (unsigned int count = 0; count != 100000u; ++count) {
        input = input * 1664525u + 1013904223u;
        if (check(input))
            return 1;
    }
    puts("362144 inputs x two byte-swap paths: PASS");
    return 0;
}
