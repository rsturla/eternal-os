#include <builtins.h>
#include <config.h>
#include <shell.h>
#include <stdio.h>
static int eternal_builtin(WORD_LIST *list) {
  (void)list;
  puts("eternal builtin");
  return EXECUTION_SUCCESS;
}
char *eternal_doc[] = {"Print the fixture response.", 0};
struct builtin eternal_struct = {"eternal",   eternal_builtin, BUILTIN_ENABLED,
                                 eternal_doc, "eternal",       0};
