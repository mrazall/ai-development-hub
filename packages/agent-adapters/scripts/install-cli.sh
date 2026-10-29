#!/usr/bin/env bash
set -euo pipefail

dry_run=0
target=""
node_version="${NODE_VERSION:-v22.14.0}"
for argument in "$@"; do
  case "$argument" in
    --dry-run) dry_run=1 ;;
    claude|codex|node) target="$argument" ;;
    *) echo "usage: $0 <claude|codex|node> [--dry-run]" >&2; exit 2 ;;
  esac
done

if [[ -z "$target" ]]; then
  echo "usage: $0 <claude|codex|node> [--dry-run]" >&2
  exit 2
fi

case "$target" in
  claude) command='curl -fsSL https://claude.ai/install.sh | bash' ;;
  codex) command='mkdir -p "$HOME/.local" && npm i -g --prefix "$HOME/.local" @openai/codex' ;;
  node) command="download and verify node-${node_version} official archive using SHASUMS256.txt, then install into \"\$HOME/.local\"" ;;
esac
echo "$command"
if (( dry_run )); then
  exit 0
fi

case "$target" in
  claude) curl -fsSL https://claude.ai/install.sh | bash ;;
  codex)
    mkdir -p "$HOME/.local"
    npm i -g --prefix "$HOME/.local" @openai/codex
    ;;
  node)
    arch="$(uname -m)"
    case "$arch" in
      x86_64) node_arch="x64" ;;
      aarch64|arm64) node_arch="arm64" ;;
      *) echo "unsupported Node.js architecture: $arch" >&2; exit 1 ;;
    esac
    platform="linux-$node_arch"
    base="https://nodejs.org/dist/$node_version"
    archive="node-$node_version-$platform.tar.xz"
    tmp_dir="$(mktemp -d)"
    trap 'rm -rf "$tmp_dir"' EXIT
    curl -fsSL "$base/$archive" -o "$tmp_dir/$archive"
    curl -fsSL "$base/SHASUMS256.txt" -o "$tmp_dir/SHASUMS256.txt"
    expected="$(awk -v file="$archive" '$2 == file {print $1; exit}' "$tmp_dir/SHASUMS256.txt")"
    [[ -n "$expected" ]] || { echo "archive checksum is missing" >&2; exit 1; }
    actual="$(sha256sum "$tmp_dir/$archive" | awk '{print $1}')"
    [[ "$actual" == "$expected" ]] || { echo "Node.js archive checksum mismatch" >&2; exit 1; }
    mkdir -p "$HOME/.local"
    tar -xJf "$tmp_dir/$archive" --strip-components=1 -C "$HOME/.local"
    ;;
esac
