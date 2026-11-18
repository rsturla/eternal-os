/* A volatile stack array keeps the canary observable, even with optimization. */
static int guarded(unsigned index)
{
  volatile unsigned char values[32];
  index %= sizeof values;
  values[index] = 42;
  return values[index];
}

int main(int argc, char **argv)
{
  (void)argv;
  return guarded((unsigned)argc) != 42;
}
