#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#define CHECK(expr)                                                            \
  do {                                                                         \
    if (!(expr)) {                                                             \
      fprintf(stderr, "%s:%d: %s failed\n", __FILE__, __LINE__, #expr);        \
      return 1;                                                                \
    }                                                                          \
  } while (0)
#include <expat.h>
static void start(void *data, const char *name, const char **attributes) {
  (void)attributes;
  if (!strcmp(name, "item"))
    ++*(int *)data;
}
int main(void) {
  XML_Parser p = XML_ParserCreate(NULL);
  int count = 0;
  CHECK(p);
  XML_SetUserData(p, &count);
  XML_SetStartElementHandler(p, start);
  CHECK(XML_Parse(p, "<root><item/>", 13, 0) == XML_STATUS_OK);
  CHECK(XML_Parse(p, "<item/></root>", 14, 1) == XML_STATUS_OK);
  CHECK(count == 2);
  XML_ParserFree(p);
  p = XML_ParserCreate(NULL);
  CHECK(p);
  CHECK(XML_Parse(p, "<root></wrong>", 14, 1) == XML_STATUS_ERROR);
  CHECK(XML_GetErrorCode(p) == XML_ERROR_TAG_MISMATCH);
  XML_ParserFree(p);
  return 0;
}
