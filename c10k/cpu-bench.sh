#!/usr/bin/env bash
# 重い計算を入れた比較ベンチ。1リクエストごとに WORK_MS ミリ秒のCPU計算をさせ、
# 各サーバーが1秒に何件捌けるか、CPUを何コア使えたかを測る。
#
#   ./c10k/cpu-bench.sh
#   WORK_MS=2 C=128 ./c10k/cpu-bench.sh
set -u
cd "$(dirname "$0")/.."

export WORK_MS=${WORK_MS:-1}
C=${C:-64}
DURATION=${DURATION:-5s}
PY=${PY:-python3}

BIN=$(mktemp -d)
trap 'rm -rf "$BIN"' EXIT
go build -o "$BIN/cpuload" ./c10k/go/cpuload || exit 1
go build -o "$BIN/goroutine" ./c10k/go/goroutine || exit 1
go build -o "$BIN/kqueue" ./c10k/go/kqueue || exit 1

echo "WORK_MS=$WORK_MS connections=$C duration=$DURATION cpus=$(sysctl -n hw.ncpu)"
echo

run() { # 名前 アドレス サーバー起動コマンド...
  local name=$1 addr=$2
  shift 2
  echo "===== $name ====="
  "$@" >"$BIN/$name.log" 2>&1 &
  local pid=$!
  # 起動時にCPU計算の量を測るので、その分待つ。
  sleep 2
  "$BIN/cpuload" -addr "$addr" -c "$C" -duration "$DURATION" -pid "$pid"
  kill "$pid" 2>/dev/null
  wait "$pid" 2>/dev/null
  echo
}

run py-threads     127.0.0.1:9101 "$PY" c10k/python/threads.py
run py-select-loop 127.0.0.1:9102 "$PY" c10k/python/select_loop.py
run py-asyncio     127.0.0.1:9103 "$PY" c10k/python/async_server.py
run go-os-thread   127.0.0.1:9201 "$BIN/goroutine" -addr 127.0.0.1:9201 -lock-os-thread
run go-goroutine   127.0.0.1:9200 "$BIN/goroutine" -addr 127.0.0.1:9200
run go-kqueue      127.0.0.1:9202 "$BIN/kqueue"
