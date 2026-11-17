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
#include <sqlite3.h>
int main(void) {
  sqlite3 *db = NULL;
  sqlite3_stmt *s = NULL;
  CHECK(sqlite3_open("database.sqlite", &db) == SQLITE_OK);
  CHECK(sqlite3_exec(db,
                     "CREATE TABLE t(id INTEGER PRIMARY KEY, v TEXT UNIQUE); "
                     "BEGIN; INSERT INTO t VALUES(1,'rolled back'); ROLLBACK;",
                     NULL, NULL, NULL) == SQLITE_OK);
  CHECK(sqlite3_prepare_v2(db, "SELECT count(*) FROM t", -1, &s, NULL) ==
        SQLITE_OK);
  CHECK(sqlite3_step(s) == SQLITE_ROW && sqlite3_column_int(s, 0) == 0);
  CHECK(sqlite3_finalize(s) == SQLITE_OK);
  CHECK(sqlite3_prepare_v2(db, "INSERT INTO t VALUES(?,?)", -1, &s, NULL) ==
        SQLITE_OK);
  CHECK(sqlite3_bind_int(s, 1, 42) == SQLITE_OK);
  CHECK(sqlite3_bind_text(s, 2, "hello ' world", -1, SQLITE_STATIC) ==
        SQLITE_OK);
  CHECK(sqlite3_step(s) == SQLITE_DONE);
  CHECK(sqlite3_finalize(s) == SQLITE_OK);
  CHECK(sqlite3_exec(db, "INSERT INTO t VALUES(42,'duplicate')", NULL, NULL,
                     NULL) == SQLITE_CONSTRAINT);
  CHECK(sqlite3_close(db) == SQLITE_OK);
  CHECK(sqlite3_open("database.sqlite", &db) == SQLITE_OK);
  CHECK(sqlite3_prepare_v2(db, "SELECT v FROM t WHERE id=42", -1, &s, NULL) ==
        SQLITE_OK);
  CHECK(sqlite3_step(s) == SQLITE_ROW &&
        !strcmp((const char *)sqlite3_column_text(s, 0), "hello ' world"));
  CHECK(sqlite3_finalize(s) == SQLITE_OK);
  CHECK(sqlite3_exec(db,
                     "CREATE VIRTUAL TABLE search USING fts5(body); INSERT "
                     "INTO search VALUES('eternal linux');",
                     NULL, NULL, NULL) == SQLITE_OK);
  CHECK(sqlite3_prepare_v2(
            db, "SELECT count(*) FROM search WHERE search MATCH 'linux'", -1,
            &s, NULL) == SQLITE_OK);
  CHECK(sqlite3_step(s) == SQLITE_ROW && sqlite3_column_int(s, 0) == 1);
  CHECK(sqlite3_finalize(s) == SQLITE_OK);
  CHECK(sqlite3_close(db) == SQLITE_OK);
  return 0;
}
