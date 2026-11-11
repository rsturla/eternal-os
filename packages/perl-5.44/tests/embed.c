#include <EXTERN.h>
#include <perl.h>
int main(int argc, char **argv, char **env) {
  PERL_SYS_INIT3(&argc, &argv, &env);
  PerlInterpreter *p = perl_alloc();
  if (!p)
    return 1;
  perl_construct(p);
  char *args[] = {"embedded", "-e", "exit((6*7)==42 ? 0 : 1)", NULL};
  int result = perl_parse(p, NULL, 3, args, NULL);
  if (!result)
    result = perl_run(p);
  perl_destruct(p);
  perl_free(p);
  PERL_SYS_TERM();
  return result;
}
