#include <assert.h>
struct pair {
  long a, b, c, d;
};
int main(void) {
  struct pair p = {1, 2, 3, 4}, q;
  __atomic_load(&p, &q, __ATOMIC_SEQ_CST);
  assert(q.a == 1 && q.b == 2 && q.c == 3 && q.d == 4);
}
