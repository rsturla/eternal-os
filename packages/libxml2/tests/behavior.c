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
#include <libxml/parser.h>
#include <libxml/xpath.h>
int main(void) {
  const char *xml = "<root><item id='a'>42</item><item id='b'>7</item></root>";
  xmlDocPtr d =
      xmlReadMemory(xml, strlen(xml), "test.xml", NULL, XML_PARSE_NONET);
  CHECK(d);
  xmlXPathContextPtr c = xmlXPathNewContext(d);
  CHECK(c);
  xmlXPathObjectPtr v = xmlXPathEvalExpression(BAD_CAST "sum(/root/item)", c);
  CHECK(v && v->floatval == 49.0);
  xmlXPathFreeObject(v);
  v = xmlXPathEvalExpression(BAD_CAST "/root/item[@id='a']/text()", c);
  CHECK(v && v->nodesetval && v->nodesetval->nodeNr == 1);
  CHECK(!xmlStrcmp(v->nodesetval->nodeTab[0]->content, BAD_CAST "42"));
  xmlXPathFreeObject(v);
  xmlXPathFreeContext(c);
  xmlFreeDoc(d);
  CHECK(!xmlReadMemory("<root></wrong>", 14, "bad.xml", NULL,
                       XML_PARSE_NONET | XML_PARSE_NOERROR |
                           XML_PARSE_NOWARNING));
  xmlCleanupParser();
  return 0;
}
