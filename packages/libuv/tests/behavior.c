#include <fcntl.h>
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
#include <uv.h>
static int fired = 0;
static void tick(uv_timer_t *timer) {
  ++fired;
  uv_close((uv_handle_t *)timer, NULL);
}
int main(void) {
  uv_loop_t loop;
  CHECK(uv_loop_init(&loop) == 0);
  uv_timer_t timer;
  CHECK(uv_timer_init(&loop, &timer) == 0);
  CHECK(uv_timer_start(&timer, tick, 1, 0) == 0);
  CHECK(uv_run(&loop, UV_RUN_DEFAULT) == 0);
  CHECK(fired == 1);
  CHECK(uv_loop_close(&loop) == 0);
  uv_fs_t req;
  int fd = uv_fs_open(NULL, &req, "uv-data", O_CREAT | O_RDWR, 0600, NULL);
  CHECK(fd >= 0);
  uv_fs_req_cleanup(&req);
  uv_buf_t b = uv_buf_init("payload", 7);
  CHECK(uv_fs_write(NULL, &req, fd, &b, 1, 0, NULL) == 7);
  uv_fs_req_cleanup(&req);
  char text[8] = {0};
  b = uv_buf_init(text, 7);
  CHECK(uv_fs_read(NULL, &req, fd, &b, 1, 0, NULL) == 7);
  CHECK(!strcmp(text, "payload"));
  uv_fs_req_cleanup(&req);
  CHECK(uv_fs_close(NULL, &req, fd, NULL) == 0);
  uv_fs_req_cleanup(&req);
  CHECK(uv_fs_stat(NULL, &req, "missing-file", NULL) == UV_ENOENT);
  uv_fs_req_cleanup(&req);
  return 0;
}
