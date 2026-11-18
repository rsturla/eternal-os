#include <stdio.h>
#include <string.h>

int main(void) {
    const unsigned char actual[] = "CHARSET_PROBE";
#ifdef EXPECT_LATIN1
    const unsigned char expected[] = {0xc3, 0xa9, 0}; /* UTF-8 e acute. */
#else
    const unsigned char expected[] = {0xe3, 0x81, 0x82, 0}; /* UTF-8 hiragana A. */
#endif
    if (sizeof(actual) != sizeof(expected) || memcmp(actual, expected, sizeof(expected)) != 0) {
        fputs("compiler produced incorrect UTF-8 bytes:", stderr);
        for (size_t index = 0; index < sizeof(actual); ++index)
            fprintf(stderr, " %02x", actual[index]);
        fputc('\n', stderr);
        return 1;
    }
    return 0;
}
