#include <assert.h>

int counter;

__attribute__((noinline)) void increment(void) {
  __transaction_atomic { counter += 1; }
}

int main(void) {
  for (int i = 0; i < 42; ++i)
    increment();
  assert(counter == 42);
  __transaction_atomic {
    counter = -1;
    __transaction_cancel;
  }
  assert(counter == 42);
  return 0;
}
