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
#include <json/json.h>
#include <sstream>
int main() {
  Json::CharReaderBuilder reader;
  Json::Value v;
  std::string errors;
  std::istringstream input(
      "{\"answer\":42,\"items\":[true,\"hello\\nworld\"]}");
  CHECK(Json::parseFromStream(reader, input, &v, &errors));
  CHECK(v["answer"].asInt() == 42);
  CHECK(v["items"].size() == 2);
  CHECK(v["items"][1].asString() == "hello\nworld");
  Json::StreamWriterBuilder writer;
  std::istringstream roundtrip(Json::writeString(writer, v));
  Json::Value copy;
  CHECK(Json::parseFromStream(reader, roundtrip, &copy, &errors));
  CHECK(copy == v);
  std::istringstream bad("{invalid]");
  CHECK(!Json::parseFromStream(reader, bad, &copy, &errors));
  CHECK(!errors.empty());
  return 0;
}
