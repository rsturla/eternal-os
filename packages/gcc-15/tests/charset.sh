#!/usr/bin/bash
set -euo pipefail
compiler=${1:?versioned GCC command}
source=$(<"$TEST_FILES/charset.c")
# Replace an ASCII marker with real source bytes. Escape sequences inside the
# C string would bypass input decoding and would not detect disabled iconv.
for encoding in ISO-8859-1 EUC-JP; do
    defines=()
    if [[ $encoding = ISO-8859-1 ]]; then
        encoded=$'\351'
        defines=(-DEXPECT_LATIN1)
    else
        encoded=$'\244\242'
    fi
    printf '%s\n' "${source//CHARSET_PROBE/$encoded}" >encoded.c
    "$compiler" -std=c11 -Wall -Wextra -Werror \
        -finput-charset="$encoding" -fexec-charset=UTF-8 \
        "${defines[@]}" encoded.c -o charset-probe
    ./charset-probe
done
