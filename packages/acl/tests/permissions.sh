#!/usr/bin/env bash
set -Eeuo pipefail
trap 'printf "failed at %s:%s: %s\n" "${BASH_SOURCE[0]}" "$LINENO" "$BASH_COMMAND" >&2' ERR
export LC_ALL=C
: > target
uid=$(id -u)
chmod 640 target
setfacl -m u:"$uid":r-- target
[[ $(getfacl -cn target) == *"user:$uid:r--"* ]]
getfacl -n target > saved.acl
setfacl -b target
[[ $(getfacl -cn target) != *"user:$uid:"* ]]
setfacl --restore=saved.acl
[[ $(getfacl -cn target) == *"user:$uid:r--"* ]]
mkdir directory
setfacl -m d:u:"$uid":r-x directory
: > directory/inherited
[[ $(getfacl -cn directory/inherited) == *"user:$uid:r-x"* ]]
if setfacl -m invalid target; then exit 1; fi
