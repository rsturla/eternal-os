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
#include <libexslt/exslt.h>
#include <libxml/parser.h>
#include <libxslt/transform.h>
#include <libxslt/xsltutils.h>
int main(void) {
  exsltRegisterAll();
  const char *style =
      "<xsl:stylesheet version='1.0' "
      "xmlns:xsl='http://www.w3.org/1999/XSL/Transform' "
      "xmlns:math='http://exslt.org/math'><xsl:output "
      "method='text'/><xsl:template match='/'><xsl:value-of "
      "select='math:abs(-sum(/root/n))'/></xsl:template></xsl:stylesheet>";
  xmlDocPtr sd =
      xmlReadMemory(style, strlen(style), "style.xsl", NULL, XML_PARSE_NONET);
  CHECK(sd);
  xsltStylesheetPtr s = xsltParseStylesheetDoc(sd);
  CHECK(s);
  const char *input = "<root><n>19</n><n>23</n></root>";
  xmlDocPtr d =
      xmlReadMemory(input, strlen(input), "input.xml", NULL, XML_PARSE_NONET);
  CHECK(d);
  xmlDocPtr result = xsltApplyStylesheet(s, d, NULL);
  CHECK(result);
  xmlChar *text = NULL;
  int length = 0;
  CHECK(xsltSaveResultToString(&text, &length, result, s) == 0);
  CHECK(length == 2 && !memcmp(text, "42", 2));
  xmlFree(text);
  xmlFreeDoc(result);
  xmlFreeDoc(d);
  xsltFreeStylesheet(s);
  xsltCleanupGlobals();
  xmlCleanupParser();
  return 0;
}
