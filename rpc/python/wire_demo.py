"""同じリクエストを、本の JSON 形式と Protocol Buffers で表したときのバイト列を比べる。

先に ./rpc/gen.sh で calc_pb2.py を生成しておく。
"""

import json

import calc_pb2


def show(label, data):
    print('{:<28} {:>3} bytes: {}'.format(label, len(data), data.hex(' ')))


book = {'method': 'subtract', 'params': [42, 23], 'param_types': ['int', 'int'], 'id': 1}
as_json = json.dumps(book).encode()
print('{:<28} {:>3} bytes: {}'.format('本の JSON', len(as_json), as_json.decode()))

show('protobuf Subtract(42, 23)', calc_pb2.SubtractRequest(a=42, b=23).SerializeToString())
show('protobuf Subtract(300, 1)', calc_pb2.SubtractRequest(a=300, b=1).SerializeToString())
show('protobuf Subtract(0, 23)', calc_pb2.SubtractRequest(a=0, b=23).SerializeToString())
show('protobuf Reverse("hello")', calc_pb2.ReverseRequest(s='hello').SerializeToString())

# 受け取った側は、同じ .proto から作ったコードでバイト列を元に戻す。
decoded = calc_pb2.SubtractRequest.FromString(bytes.fromhex('08 2a 10 17'))
print('08 2a 10 17 を読み戻すと: a={} b={}'.format(decoded.a, decoded.b))
