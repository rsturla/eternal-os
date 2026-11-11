#!/usr/bin/env bash
# /tmp is a sandbox mount when installed; the RPM payload check covers its mode.
set -euo pipefail
root=${1%/}
fail() {
  echo "filesystem layout: $*" >&2
  exit 1
}
check_link() {
  local path="$root$1" expected=$2 actual
  [[ -L $path ]] || fail "$path: expected symlink to $expected"
  actual=$(readlink "$path")
  [[ $actual == "$expected" ]] || fail "$path: expected link $expected, got $actual"
}
check_directory() {
  local path="$root$1" expected=$2 actual
  [[ -d $path && ! -L $path ]] || fail "$path: expected a real directory"
  actual=$(stat -c %a "$path")
  [[ $actual == "$expected" ]] || fail "$path: expected mode $expected, got $actual"
}
for name in bin sbin lib lib64; do
  check_link "/$name" "usr/$name"
done
check_link /var/run ../run
check_link /var/lock ../run/lock
check_directory /tmp 1777
check_directory /var/tmp 1777
check_directory /root 700
for path in /usr/bin /usr/lib /usr/lib64 /usr/local/share /var/cache /var/lib /var/log; do
  check_directory "$path" 755
done
