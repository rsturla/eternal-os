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
#include <json-c/json.h>
int main(void) {
  struct json_object *o = json_tokener_parse(
      "{\"answer\":42,\"items\":[true,\"hello\\nworld\"],\"nothing\":null}");
  CHECK(o);
  struct json_object *v;
  CHECK(json_object_object_get_ex(o, "answer", &v));
  CHECK(json_object_get_int(v) == 42);
  CHECK(json_object_object_get_ex(o, "items", &v));
  CHECK(json_object_array_length(v) == 2);
  CHECK(json_object_get_boolean(json_object_array_get_idx(v, 0)));
  CHECK(!strcmp(json_object_get_string(json_object_array_get_idx(v, 1)),
                "hello\nworld"));
  struct json_object *copy = json_tokener_parse(
      json_object_to_json_string_ext(o, JSON_C_TO_STRING_PLAIN));
  CHECK(copy && json_object_equal(o, copy));
  json_object_put(copy);
  json_object_put(o);
  struct json_tokener *t = json_tokener_new();
  CHECK(t);
  o = json_tokener_parse_ex(t, "{broken]", 8);
  CHECK(!o && json_tokener_get_error(t) != json_tokener_success);
  json_tokener_free(t);
  return 0;
}
