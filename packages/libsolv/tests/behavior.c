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
#include <solv/knownid.h>
#include <solv/pool.h>
#include <solv/repo.h>
#include <solv/solver.h>
int main(void) {
  Pool *p = pool_create();
  CHECK(p);
  Repo *r = repo_create(p, "fixture");
  CHECK(r);
  Id id = repo_add_solvable(r);
  Solvable *s = pool_id2solvable(p, id);
  s->name = pool_str2id(p, "fixture-package", 1);
  s->evr = pool_str2id(p, "1.0", 1);
  s->arch = ARCH_NOARCH;
  s->provides = repo_addid_dep(r, s->provides, s->name, 0);
  repo_internalize(r);
  pool_createwhatprovides(p);
  Queue job;
  queue_init(&job);
  queue_push2(&job, SOLVER_INSTALL | SOLVER_SOLVABLE, id);
  Solver *solver = solver_create(p);
  CHECK(solver);
  CHECK(solver_solve(solver, &job) == 0);
  solver_free(solver);
  queue_empty(&job);
  queue_push2(&job, SOLVER_INSTALL | SOLVER_SOLVABLE_NAME,
              pool_str2id(p, "missing-package", 1));
  solver = solver_create(p);
  CHECK(solver_solve(solver, &job) > 0);
  solver_free(solver);
  queue_free(&job);
  pool_free(p);
  return 0;
}
