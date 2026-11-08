#!/usr/bin/env bash
# Validate the commits a pull request adds to the repository.
#
# Two rules are enforced for every commit in the range:
#
#   1. The message is a lowercase scope, a colon and an imperative summary:
#      "glibc-2.44: add package". The scope names the package it changes or a
#      repository area; the summary stays under 72 characters and does not end
#      with a period.
#   2. A commit changes files under at most one packages/<name>/ directory,
#      because one commit carries one package change. A change that genuinely
#      spans packages declares it with a "many: <reason>" trailer.
#
# bootstrap/recipes/ is exempt from the second rule: adding a bootstrap variant
# beside the production recipe is one logical change.
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)

subject_max=72
base=
range=
message_file=
failed=0
msg_scope=

meta_scopes=(bootstrap build ci deps docs dx metadata release repo scripts)

usage() {
  cat <<'EOF'
usage: check-commits.sh [options]

  --base REF            Check the commits since the merge base with REF
                        (default: origin/HEAD)
  --range A..B          Check an explicit revision range instead of --base
  --message-file PATH   Check a single message, for a commit-msg hook
  -h, --help            Show this help
EOF
}

while (($# > 0)); do
  case "$1" in
    --base)
      base=${2?--base needs a ref}
      # A push event reports an all-zero before-sha for a new branch.
      if [[ -z $base || $base == 0000000000000000000000000000000000000000 ]]; then
        base=
      fi
      shift 2
      ;;
    --range)
      range=${2?--range needs a revision range}
      shift 2
      ;;
    --message-file)
      message_file=${2?--message-file needs a path}
      shift 2
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      echo "unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

declare -A known_scope
declare -A is_area
for scope in "${meta_scopes[@]}"; do
  known_scope[$scope]=1
  is_area[$scope]=1
done
while IFS= read -r name; do
  [[ -n $name ]] && known_scope[$name]=1
done < <("$root/scripts/list-packages.sh")
for recipe in "$root"/bootstrap/recipes/*/package.yaml; do
  [[ -f $recipe ]] || continue
  known_scope[$(basename "$(dirname "$recipe")")]=1
done

report() {
  local label=$1 problem=$2
  failed=1
  if [[ ${GITHUB_ACTIONS:-} == true ]]; then
    printf '::error title=commit conventions::%s: %s\n' "$label" "$problem"
  fi
  printf 'error: %s: %s\n' "$label" "$problem" >&2
}

# Sets msg_scope to the parsed scope, or to the empty string when the subject
# does not follow the format.
validate_message() {
  local label=$1 message=$2
  local subject rest second summary

  subject=${message%%$'\n'*}
  rest=
  [[ $message == *$'\n'* ]] && rest=${message#*$'\n'}

  msg_scope=

  case "$subject" in
    '')
      report "$label" "empty subject"
      return 0
      ;;
    'fixup!'* | 'squash!'* | 'amend!'*)
      report "$label" "leftover '$subject'; fold it in with 'git rebase -i --autosquash'"
      return 0
      ;;
    Merge* | merge*)
      report "$label" "merge commit; rebase onto the base branch instead of merging it"
      return 0
      ;;
  esac

  ((${#subject} > subject_max)) &&
    report "$label" "subject is ${#subject} characters, the limit is $subject_max"
  [[ $subject == *" " ]] && report "$label" "subject has trailing whitespace"
  [[ $subject == *. ]] && report "$label" "subject ends with a period"

  if [[ $subject =~ ^([a-z0-9][a-z0-9._+-]*):\ (.+)$ ]]; then
    msg_scope=${BASH_REMATCH[1]}
    summary=${BASH_REMATCH[2]}
    if [[ $summary =~ ^[A-Z] ]]; then
      report "$label" "summary starts with a capital letter; use the imperative lower case"
    fi
    if [[ -z ${known_scope[$msg_scope]:-} ]]; then
      report "$label" "unknown scope '$msg_scope'; use a package name or one of: ${meta_scopes[*]}"
    fi
  else
    report "$label" "subject is not '<scope>: <summary>' (lowercase scope, colon, space, summary)"
  fi

  if [[ -n $rest ]]; then
    second=${rest%%$'\n'*}
    if [[ -n ${second//[[:space:]]/} ]]; then
      report "$label" "the second line must be blank; leave an empty line before the body"
    fi
  fi
}

validate_packages() {
  local label=$1 sha=$2 message=$3 scope=$4
  local path rest name
  local -a dirs=()

  while IFS= read -r path; do
    [[ $path == packages/* ]] || continue
    rest=${path#packages/}
    [[ $rest == */* ]] || continue
    name=${rest%%/*}
    dirs+=("$name")
  done < <(git -C "$root" diff-tree --no-commit-id --name-only -r --root "$sha")

  ((${#dirs[@]} > 0)) || return 0
  mapfile -t dirs < <(printf '%s\n' "${dirs[@]}" | sort -u)

  if ((${#dirs[@]} == 1)); then
    # One package: its scope must name it, unless the scope is a repository
    # area that legitimately touches recipes in passing.
    [[ -n $scope ]] || return 0
    [[ -n ${is_area[$scope]:-} ]] && return 0
    [[ $scope == "${dirs[0]}" ]] || report "$label" "changes packages/${dirs[0]}/ but is scoped '$scope'"
    return 0
  fi

  if ! grep -qE '^many: [^[:space:]]' <<<"$message"; then
    report "$label" "changes ${#dirs[@]} packages (${dirs[*]}); split it into one commit per package or add a 'many: <reason>' trailer"
  fi
}

if [[ -n $message_file ]]; then
  if [[ ! -f $message_file ]]; then
    echo "no such message file: $message_file" >&2
    exit 2
  fi
  message=$(sed -e '/^# ------------------------ >8 ------------------------/,$d' -e '/^#/d' "$message_file")
  validate_message "commit message" "$message"
  exit "$failed"
fi

if [[ -n $range ]]; then
  commits=$(git -C "$root" rev-list --reverse "$range")
else
  if [[ -z $base ]]; then
    for candidate in origin/HEAD origin/main main; do
      if git -C "$root" rev-parse --verify --quiet "$candidate" >/dev/null; then
        base=$candidate
        break
      fi
    done
  fi
  if [[ -z $base ]]; then
    echo "no base ref found; nothing to check" >&2
    exit 0
  fi
  merge_base=$(git -C "$root" merge-base "$base" HEAD 2>/dev/null || true)
  if [[ -z $merge_base ]]; then
    echo "cannot find a merge base for '$base'; nothing to check" >&2
    exit 0
  fi
  commits=$(git -C "$root" rev-list --reverse "$merge_base..HEAD")
fi

count=0
while IFS= read -r sha; do
  [[ -n $sha ]] || continue
  message=$(git -C "$root" log -1 --format=%B "$sha")
  validate_message "${sha:0:7}" "$message"
  validate_packages "${sha:0:7}" "$sha" "$message" "$msg_scope"
  count=$((count + 1))
done <<<"$commits"

if ((failed)); then
  echo "commit conventions failed; see docs/git-workflow.md" >&2
  exit 1
fi

echo "checked $count commit(s)"
