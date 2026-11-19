#include <stdio.h>
extern int answer(void);
int main(void) {
  printf("%d\n", answer());
  return answer() != 42;
}
