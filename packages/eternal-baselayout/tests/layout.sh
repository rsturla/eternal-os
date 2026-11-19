#!/usr/bin/env bash
# Verify RPM payload or installed paths against the directory policy.
set -euo pipefail
root=${1%/}
fail() {
  echo "eternal-baselayout: $*" >&2
  exit 1
}
check_mode() {
  local path=$1 expected_mode=$2 mode
  mode=$(stat -c %a "$path")
  [[ $mode == "$expected_mode" ]] ||
    fail "$path: expected mode $expected_mode, got $mode"
}
for entry in \
  '755 /etc/eternal' \
  '755 /usr/lib/eternal' \
  '755 /usr/share/eternal' \
  '755 /var/lib/eternal' \
  '750 /var/log/eternal'; do
  read -r mode relative <<< "$entry"
  path="$root$relative"
  [[ -d $path && ! -L $path ]] || fail "$path: expected a real directory"
  check_mode "$path" "$mode"
done
marker="$root/usr/lib/eternal/baselayout"
[[ -f $marker && ! -L $marker ]] || fail "$marker: expected a regular marker file"
check_mode "$marker" 644
expected=$(printf 'Eternal Linux base layout\n' | sha256sum)
actual=$(sha256sum "$marker")
[[ ${actual%% *} == "${expected%% *}" ]] ||
  fail "$marker: expected exactly 'Eternal Linux base layout' followed by a newline"
