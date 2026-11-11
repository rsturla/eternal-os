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
#include <gio/gio.h>
#include <glib.h>
int main(void) {
  GHashTable *h = g_hash_table_new(g_str_hash, g_str_equal);
  g_hash_table_insert(h, "answer", GINT_TO_POINTER(42));
  CHECK(GPOINTER_TO_INT(g_hash_table_lookup(h, "answer")) == 42);
  CHECK(!g_hash_table_contains(h, "missing"));
  g_hash_table_destroy(h);
  CHECK(g_utf8_validate("M\303\274nchen", -1, NULL));
  CHECK(!g_utf8_validate("\377", 1, NULL));
  GVariant *v = g_variant_ref_sink(g_variant_new("(si)", "answer", 42));
  const char *s;
  gint32 n;
  g_variant_get(v, "(&si)", &s, &n);
  CHECK(!strcmp(s, "answer") && n == 42);
  g_variant_unref(v);
  GError *error = NULL;
  gchar *contents = NULL;
  gsize size = 0;
  CHECK(g_file_set_contents("gio-data", "payload", 7, &error));
  CHECK(g_file_get_contents("gio-data", &contents, &size, &error));
  CHECK(size == 7 && !memcmp(contents, "payload", 7));
  g_free(contents);
  CHECK(!g_file_get_contents("nonexistent-fixture", &contents, &size, &error));
  CHECK(error && error->domain == G_FILE_ERROR);
  g_error_free(error);
  error = NULL;
  /* Exercise GObject ownership without depending on a desktop session. */
  GObject *object = g_object_new(G_TYPE_OBJECT, NULL);
  CHECK(object);
  g_object_set_data(object, "answer", GINT_TO_POINTER(42));
  CHECK(GPOINTER_TO_INT(g_object_get_data(object, "answer")) == 42);
  gpointer weak = object;
  g_object_add_weak_pointer(object, &weak);
  g_object_unref(object);
  CHECK(weak == NULL);

  /* GIO reads known bytes, then reports EOF and a closed-stream error. */
  GInputStream *stream =
      g_memory_input_stream_new_from_data("payload", 7, NULL);
  CHECK(stream);
  char buffer[8] = {0};
  CHECK(g_input_stream_read(stream, buffer, sizeof buffer, NULL, &error) == 7);
  CHECK(!memcmp(buffer, "payload", 7) && error == NULL);
  CHECK(g_input_stream_read(stream, buffer, sizeof buffer, NULL, &error) == 0);
  CHECK(g_input_stream_close(stream, NULL, &error));
  CHECK(g_input_stream_read(stream, buffer, sizeof buffer, NULL, &error) == -1);
  CHECK(g_error_matches(error, G_IO_ERROR, G_IO_ERROR_CLOSED));
  g_clear_error(&error);
  g_object_unref(stream);
  return 0;
}
