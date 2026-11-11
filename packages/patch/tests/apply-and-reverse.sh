#!/usr/bin/env bash
set -Eeuo pipefail
trap 'printf "failed at %s:%s: %s\n" "${BASH_SOURCE[0]}" "$LINENO" "$BASH_COMMAND" >&2' ERR
export LC_ALL=C
printf 'alpha\nbeta\n' > original
cp original working
cat > change.patch <<'EOF'
--- working
+++ working
@@ -1,2 +1,2 @@
 alpha
-beta
+gamma
EOF
patch --batch --dry-run -p0 < change.patch
cmp original working
patch --batch -p0 < change.patch
[[ $(cat working) == $'alpha\ngamma' ]]
patch --batch -R -p0 < change.patch
cmp original working
printf unrelated > working
if patch --batch --forward -p0 < change.patch; then exit 1; fi
[[ -s working.rej ]]
