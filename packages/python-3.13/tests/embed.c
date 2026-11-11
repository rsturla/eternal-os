#include <Python.h>
int main(void) {
  Py_Initialize();
  int result =
      PyRun_SimpleString("import json, sys; assert json.loads('[42]') == [42]");
  return Py_FinalizeEx() < 0 || result != 0;
}
