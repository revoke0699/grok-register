#!/bin/sh
set -eu

export DEBIAN_FRONTEND="${DEBIAN_FRONTEND:-noninteractive}"

mkdir -p /etc/apt/apt.conf.d
cat > /etc/apt/apt.conf.d/80-retries <<'CONF'
Acquire::Retries "5";
Acquire::http::Timeout "60";
Acquire::https::Timeout "60";
Acquire::http::Pipeline-Depth "0";
CONF

attempt=1
max_attempts=5
while :; do
  rm -rf /var/lib/apt/lists/*
  if apt-get update && apt-get install -y --no-install-recommends "$@"; then
    break
  fi
  if [ "$attempt" -ge "$max_attempts" ]; then
    echo "apt-get failed after ${max_attempts} attempts" >&2
    exit 1
  fi
  echo "apt-get failed, retry ${attempt}/${max_attempts}" >&2
  sleep $((attempt * 8))
  attempt=$((attempt + 1))
done

rm -rf /var/lib/apt/lists/*
