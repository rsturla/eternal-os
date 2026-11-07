#!/usr/bin/env bash
# Start a recipe from the rpmx template and point it at the repository's
# bootstrap profile.
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
rpmx=${RPMX:-rpmx}
template=c

usage() {
  cat <<'EOF'
usage: new-package.sh NAME [--template c|python|metapackage]

NAME is a directory under packages/, for example `packages/foo` or `foo`.
EOF
}

[[ $# -gt 0 ]] || {
  usage >&2
  exit 2
}

name=$1
shift
while (($# > 0)); do
  case "$1" in
    --template)
      template=${2:?--template needs a value}
      shift 2
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      echo "unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

name=${name#./}
[[ $name == packages/* ]] || name="packages/$name"
directory="$root/$name"

if [[ -e $directory ]]; then
  echo "refusing to overwrite existing directory: ${directory#"$root"/}" >&2
  exit 1
fi

"$rpmx" init "$directory" --template "$template"

# The repository owns the profile; a per-package copy would drift.
rm -rf "$directory/profiles" "$directory/.gitignore" "$directory/README.md"

sed -i \
  's|profile: fedora-44|profile: ../../profiles/bootstrap.profile.yaml|' \
  "$directory/package.yaml"
# Maintainers are repository defaults; keep the generated recipe lean.
sed -i '/^  maintainers:$/,/^      email:/d' "$directory/package.yaml"

echo "created ${directory#"$root"/}/package.yaml"
echo "next: edit the recipe, then run ./scripts/lint-all.sh"
