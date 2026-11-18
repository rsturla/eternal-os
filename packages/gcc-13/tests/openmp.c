#include <assert.h>
#include <omp.h>
int main(void) {
  int sum = 0;
#pragma omp parallel for reduction(+ : sum) num_threads(2)
  for (int i = 0; i < 100; ++i)
    sum += i;
  assert(sum == 4950);
  return 0;
}
