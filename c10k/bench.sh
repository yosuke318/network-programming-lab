#!/usr/bin/env bash
# C10K 比較ベンチ。各サーバーを起動 → loadgen で N 本の接続を張る → 計測 → 停止、を順に行う。
#
#   ./c10k/bench.sh                 全部
#   ./c10k/bench.sh go-kqueue       名前を指定したものだけ
#   N=2000 COOLDOWN=0 ./c10k/bench.sh
set -u
cd "$(dirname "$0")/.."

N=${N:-10000}
# 直列サーバーは1人ずつしか捌けず、残りは接続タイムアウトを待つだけになるので本数を減らす。
N_SEQ=${N_SEQ:-300}
# 前の回の接続が TIME_WAIT で送信元ポートを握ったままになるので、明けるまで待つ（macOS は約30秒）。
COOLDOWN=${COOLDOWN:-35}
PY=${PY:-python3}

BIN=$(mktemp -d)
trap 'rm -rf "$BIN"' EXIT
go build -o "$BIN/loadgen" ./c10k/go/loadgen || exit 1
go build -o "$BIN/goroutine" ./c10k/go/goroutine || exit 1
go build -o "$BIN/kqueue" ./c10k/go/kqueue || exit 1

first=1
run() { # 名前 アドレス 接続数 サーバー起動コマンド...
  local name=$1 addr=$2 n=$3
  shift 3
  if [ -n "${ONLY:-}" ] && [ "$ONLY" != "$name" ]; then return; fi
  if [ $first -eq 0 ]; then sleep "$COOLDOWN"; fi
  first=0

  echo "===== $name ====="
  "$@" >"$BIN/$name.log" 2>&1 &
  local pid=$!
  sleep 1
  "$BIN/loadgen" -addr "$addr" -n "$n" -pid "$pid"
  kill "$pid" 2>/dev/null
  wait "$pid" 2>/dev/null
  echo "--- server log ---"
  grep -v '^\s*$' "$BIN/$name.log" | head -4
  echo
}

ONLY=${1:-}

run py-sequential  127.0.0.1:9100 "$N_SEQ" "$PY" c10k/python/sequential.py
run py-threads     127.0.0.1:9101 "$N"     "$PY" c10k/python/threads.py
run py-select-loop 127.0.0.1:9102 "$N"     "$PY" c10k/python/select_loop.py
run py-asyncio     127.0.0.1:9103 "$N"     "$PY" c10k/python/async_server.py
run go-goroutine   127.0.0.1:9200 "$N"     "$BIN/goroutine" -addr 127.0.0.1:9200
run go-os-thread   127.0.0.1:9201 "$N"     env GOTRACEBACK=none "$BIN/goroutine" -addr 127.0.0.1:9201 -lock-os-thread
run go-kqueue      127.0.0.1:9202 "$N"     "$BIN/kqueue"
