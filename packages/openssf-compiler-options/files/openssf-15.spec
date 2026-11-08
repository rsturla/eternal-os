# OpenSSF compiler hardening for GCC 15 and newer. Structure padding is
# zero-initialised as well as automatic variables.
*self_spec:
+ %{!O:%{!O1:%{!O2:%{!O3:%{!O0:%{!Os:%{!Ofast:%{!Og:%{!Oz:-O2}}}}}}}}} \
  %{!g:%{!g0:%{!g1:%{!g2:%{!g3:-g}}}}} \
  -pipe \
  %{!Wall:%{!Wno-all:-Wall}} \
  -Werror=format-security \
  %{!fno-exceptions:-fexceptions} \
  %{!fno-asynchronous-unwind-tables:-fasynchronous-unwind-tables} \
  %{!gno-record-gcc-switches:-grecord-gcc-switches} \
  -U_FORTIFY_SOURCE \
  -D_FORTIFY_SOURCE=3 \
  -D_GLIBCXX_ASSERTIONS \
  -fstack-protector-strong \
  -fstack-clash-protection \
  -ftrivial-auto-var-init=zero \
  -fzero-init-padding-bits=all \
  %{!fpie:%{!fPIE:%{!fpic:%{!fPIC:%{!fno-pic:%{!fno-pie:-fPIE}}}}}} \
  %{!fdelete-null-pointer-checks:-fno-delete-null-pointer-checks} \
  -fno-strict-overflow \
  -fno-strict-aliasing \
  %{!fomit-frame-pointer:-fno-omit-frame-pointer} \
  -mno-omit-leaf-frame-pointer \
  %{!static:%{!shared:%{!r:-pie}}}

*link:
+ --as-needed \
  -O1 \
  --sort-common \
  -z noexecstack \
  -z relro \
  -z now \
  -z pack-relative-relocs \
  --build-id=sha1 \
  --error-rwx-segments \
  --error-execstack
