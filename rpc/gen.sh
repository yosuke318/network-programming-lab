#!/usr/bin/env bash
# calc.proto から Python 用のコードを生成する。
# Node.js 側は実行時に .proto を直接読むので、生成は要らない。
set -eu
cd "$(dirname "$0")/.."

./.venv/bin/python -m grpc_tools.protoc \
  -I rpc/proto \
  --python_out=rpc/python \
  --pyi_out=rpc/python \
  --grpc_python_out=rpc/python \
  rpc/proto/calc.proto

echo "generated: $(ls rpc/python/calc_pb2*)"
