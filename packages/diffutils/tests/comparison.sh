#!/usr/bin/env bash
set -Eeuo pipefail
trap 'printf "failed at %s:%s: %s\n" "${BASH_SOURCE[0]}" "$LINENO" "$BASH_COMMAND" >&2' ERR
export LC_ALL=C
printf 'alpha\nbeta\n' > old
printf 'alpha\ngamma\n' > new
status=0; diff -u old new > change || status=$?
[[ $status == 1 ]]
[[ $(cat change) == *$'-beta\n+gamma'* ]]
status=0; cmp old new > cmp.log || status=$?
[[ $status == 1 ]]
diff old old
cmp old old
printf 'alpha\nbeta\n' > sorted-old
printf 'alpha\ngamma\n' > sorted-new
[[ $(sdiff -s sorted-old sorted-new) == *beta*gamma* ]]
diff3 old old new > merge.log
[[ $(cat merge.log) == *'gamma'* ]]
status=0; diff nonexistent old > missing.log 2>&1 || status=$?
[[ $status == 2 ]]
