#!/bin/sh
set -eu

secrets_dir=${1:-infra/secrets}
umask 077
mkdir -p "$secrets_dir"

create_secret() {
    path=$1
    if [ ! -e "$path" ]; then
        openssl rand -base64 48 >"$path"
    elif [ ! -f "$path" ]; then
        echo "secret path is not a regular file: $path" >&2
        exit 1
    fi
}

create_secret "$secrets_dir/postgres_password"
create_secret "$secrets_dir/control_secret_key"
create_secret "$secrets_dir/internal_secret"
