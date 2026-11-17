#include <Python.h>
static PyObject *answer(PyObject *self, PyObject *args) {
  (void)self;
  (void)args;
  return PyLong_FromLong(42);
}
static PyMethodDef methods[] = {
    {"answer", answer, METH_NOARGS, "Return the answer"},
    {NULL, NULL, 0, NULL}};
static struct PyModuleDef module = {
    PyModuleDef_HEAD_INIT, "probe", NULL, -1, methods, NULL, NULL, NULL, NULL};
PyMODINIT_FUNC PyInit_probe(void) { return PyModule_Create(&module); }
