#include <bzlib.h>
#include <stdio.h>
#include <string.h>

#define CHECK(condition) do { \
    if (!(condition)) { \
        fprintf(stderr, "line %d: %s\n", __LINE__, #condition); \
        return 1; \
    } \
} while (0)

int main(void)
{
    char input[] = "Eternal bzip2 consumer\0binary payload\377";
    char compressed[256], restored[sizeof input];
    unsigned int compressed_size = sizeof compressed;
    unsigned int restored_size = sizeof restored;
    CHECK(BZ2_bzBuffToBuffCompress(compressed, &compressed_size,
          input, sizeof input, 9, 0, 30) == BZ_OK);
    CHECK(BZ2_bzBuffToBuffDecompress(restored, &restored_size,
          compressed, compressed_size, 0, 0) == BZ_OK);
    CHECK(restored_size == sizeof input);
    CHECK(memcmp(input, restored, sizeof input) == 0);
    return 0;
}
