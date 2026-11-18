/* GCC gcc.target/i386/pr115102.c, PR target/115102.
   Keep separate from the oracle and compile at the original -Os. */
unsigned int bswap8(unsigned int value) {
    return (value & 0xffff0000u) | ((value & 0xff00u) >> 8)
        | ((value & 0xffu) << 8);
}
