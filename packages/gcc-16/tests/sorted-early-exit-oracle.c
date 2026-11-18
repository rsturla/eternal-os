#include <limits.h>
#include <stdio.h>

extern int original_is_sorted(int *, int);
#ifdef WRONG_IMPLEMENTATION
/* The test must reject an implementation that misses every inversion. */
int optimized_is_sorted(int *data, int length)
{
  (void)data;
  (void)length;
  return 1;
}
#else
extern int optimized_is_sorted(int *, int);
#endif

static unsigned state = 0x6d5a1234u;

static unsigned next_random(void)
{
  state ^= state << 13;
  state ^= state >> 17;
  state ^= state << 5;
  return state;
}

/* Compile this independent loop at O0, separately from the optimized code. */
static int oracle(int *data, int length)
{
  for (int next = 1; next < length; ++next)
    if (data[next - 1] > data[next])
      return 0;
  return 1;
}

static int check(int *data, int length, unsigned case_number)
{
  int expected = oracle(data, length);
  int original = original_is_sorted(data, length);
  int optimized = optimized_is_sorted(data, length);
  if (original != expected || optimized != expected) {
    fprintf(stderr, "case=%u length=%d expected=%d original=%d optimized=%d\n",
            case_number, length, expected, original, optimized);
    return 1;
  }
  return 0;
}

int main(void)
{
  int data[257];
  unsigned cases = 0;

  /* These lengths must return before dereferencing the input pointer. */
  for (int length = -2; length <= 1; ++length)
    if (check(NULL, length, cases++))
      return 1;

  /* Cross vector boundaries and tails with ordered and constant inputs. */
  for (int length = 0; length <= 257; ++length) {
    for (int mode = 0; mode < 5; ++mode) {
      for (int i = 0; i < length; ++i)
        data[i] = mode == 0 ? i : mode == 1 ? -i : mode == 2 ? 0
            : mode == 3 ? INT_MAX : INT_MIN;
      if (check(data, length, cases++))
        return 1;
    }
    /* Force an early exit at each possible adjacent inversion. */
    for (int position = 1; position < length; ++position) {
      for (int i = 0; i < length; ++i)
        data[i] = i;
      int temporary = data[position];
      data[position] = data[position - 1];
      data[position - 1] = temporary;
      if (check(data, length, cases++))
        return 1;
    }
  }

  /* A fixed seed makes failures reproducible. */
  for (unsigned trial = 0; trial < 10000; ++trial) {
    int length = (int)(next_random() % 258u);
    for (int i = 0; i < length; ++i)
      data[i] = (int)next_random();
    if (check(data, length, cases++))
      return 1;
  }
  printf("is_sorted oracle passed %u cases\n", cases);
  return 0;
}
