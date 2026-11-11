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
#include <ffi.h>
static int add(int a, int b) { return a + b; }
static double mixed(double a, int b, float c) { return a + b + c; }
static void closure_add(ffi_cif *cif, void *result, void **arguments,
                        void *data) {
  (void)cif;
  *(int *)result = *(int *)arguments[0] + *(int *)data;
}
int main(void) {
  ffi_cif cif;
  ffi_type *types[] = {&ffi_type_sint, &ffi_type_sint};
  int a = 19, b = 23;
  void *values[] = {&a, &b};
  ffi_arg result = 0;
  CHECK(ffi_prep_cif(&cif, FFI_DEFAULT_ABI, 2, &ffi_type_sint, types) ==
        FFI_OK);
  ffi_call(&cif, FFI_FN(add), &result, values);
  CHECK((int)result == 42);
  /* Floating and integer arguments use different ABI register classes. */
  ffi_type *mixed_types[] = {&ffi_type_double, &ffi_type_sint, &ffi_type_float};
  double fraction = 0.5, mixed_result = 0;
  float remainder = 0.25f;
  int whole = 41;
  void *mixed_values[] = {&fraction, &whole, &remainder};
  CHECK(ffi_prep_cif(&cif, FFI_DEFAULT_ABI, 3, &ffi_type_double, mixed_types) ==
        FFI_OK);
  ffi_call(&cif, FFI_FN(mixed), &mixed_result, mixed_values);
  CHECK(mixed_result == 41.75);
  CHECK(ffi_prep_cif(&cif, (ffi_abi)-1, 0, &ffi_type_void, NULL) ==
        FFI_BAD_ABI);
  ffi_cif callback_cif;
  ffi_type *callback_types[] = {&ffi_type_sint};
  CHECK(ffi_prep_cif(&callback_cif, FFI_DEFAULT_ABI, 1, &ffi_type_sint,
                     callback_types) == FFI_OK);
  void *executable = NULL;
  ffi_closure *closure = ffi_closure_alloc(sizeof *closure, &executable);
  CHECK(closure && executable);
  int offset = 23;
  CHECK(ffi_prep_closure_loc(closure, &callback_cif, closure_add, &offset,
                             executable) == FFI_OK);
  int (*callback)(int) = (int (*)(int))executable;
  CHECK(callback(19) == 42);
  ffi_closure_free(closure);
  return 0;
}
