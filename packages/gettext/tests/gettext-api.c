#include <gettext-po.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* libgettextpo requires both callbacks even for a valid catalog. */
static void diagnostic(int severity, po_message_t message, const char *filename,
                       size_t line, size_t column, int multiline,
                       const char *text) {
  (void)message;
  (void)column;
  (void)multiline;
  fprintf(stderr, "gettext diagnostic: %s:%zu: %s\n",
          filename ? filename : "unknown", line, text);
  if (severity >= PO_SEVERITY_ERROR)
    exit(10 + severity);
}

static void diagnostic_pair(int severity, po_message_t message1,
                            const char *filename1, size_t line1, size_t column1,
                            int multiline1, const char *text1,
                            po_message_t message2, const char *filename2,
                            size_t line2, size_t column2, int multiline2,
                            const char *text2) {
  diagnostic(severity, message1, filename1, line1, column1, multiline1, text1);
  diagnostic(severity, message2, filename2, line2, column2, multiline2, text2);
}

int main(int argc, char **argv) {
  if (argc != 2)
    return 1;
  struct po_xerror_handler handler = {diagnostic, diagnostic_pair};
  po_file_t file = po_file_read(argv[1], &handler);
  if (!file)
    return 2;
  po_message_iterator_t iterator = po_message_iterator(file, NULL);
  if (!iterator)
    return 3;
  po_message_t message;
  int found = 0;
  while ((message = po_next_message(iterator)) != NULL) {
    if (strcmp(po_message_msgid(message), "hello") == 0) {
      if (strcmp(po_message_msgstr(message), "bonjour") != 0)
        return 4;
      found = 1;
    }
  }
  po_message_iterator_free(iterator);
  po_file_free(file);
  return !found;
}
