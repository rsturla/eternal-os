/* GCC gcc.target/i386/xchg-4.c. Compile at the original -O2.
   PR tree-optimization/121298 misses the compact instruction sequence. */
void ext(int value);
void foo(int value) {
    ext((value & ~0xffff) | ((value >> 8) & 0xff)
        | ((value & 0xff) << 8));
}
