"""Exercise GCC's unwinder through an installed runtime, without a compiler."""
import ctypes
from pathlib import Path
import sys

library = Path(sys.argv[1])
assert library.is_absolute() and library.is_file(), library
runtime = ctypes.CDLL(str(library))
trace_type = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
runtime._Unwind_Backtrace.argtypes = [trace_type, ctypes.c_void_p]
runtime._Unwind_Backtrace.restype = ctypes.c_int
runtime._Unwind_GetIP.argtypes = [ctypes.c_void_p]
runtime._Unwind_GetIP.restype = ctypes.c_size_t

# Exceptions cannot cross a ctypes callback boundary. Record callback problems
# and assert them after the foreign call returns instead of raising inside it.
frames = []
problems = []

@trace_type
def trace(context, argument):
    try:
        if not context:
            problems.append("unwinder supplied a null context")
            return 5
        frames.append(runtime._Unwind_GetIP(context))
        if len(frames) > 128:
            problems.append("unwinder exceeded the bounded stack traversal")
            return 5
        return 0
    except Exception as error:
        problems.append(str(error))
        return 5

status = runtime._Unwind_Backtrace(trace, None)
assert not problems, problems
assert status == 5, f"backtrace returned {status}, expected END_OF_STACK=5"
assert 2 <= len(frames) <= 128, f"unexpected frame count: {len(frames)}"
assert sum(address != 0 for address in frames) >= 2, frames

# GCC maps a trace callback's stop request to FATAL_PHASE1_ERROR. Verify that
# it honors the stop immediately rather than continuing through more frames.
stopped = []

@trace_type
def stop(context, argument):
    stopped.append(bool(context))
    return 5

status = runtime._Unwind_Backtrace(stop, None)
assert status == 3, f"callback stop returned {status}, expected FATAL_PHASE1_ERROR=3"
assert stopped == [True], f"callback was not stopped after one frame: {stopped}"
print("libgcc-unwind-ok")
