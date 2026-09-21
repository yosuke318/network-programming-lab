"""calc.proto の Calculator サービスを提供する gRPC サーバー。

本の課題では「ソケットを作ってバインドするクラス」と「リクエストを処理して返すクラス」を
分けて書くよう勧めている。gRPC では前者（ソケット、メッセージの区切り、どの関数を呼ぶかの
振り分け）をライブラリと生成コードが受け持つので、自分で書くのは後者の中身だけになる。

先に ./rpc/gen.sh で calc_pb2.py と calc_pb2_grpc.py を生成しておく。
"""

import math
import os
from concurrent import futures

import grpc
from google.protobuf import text_format

import calc_pb2
import calc_pb2_grpc

SOCKET_PATH = '/tmp/calc.sock'


def log(method, request):
    print('{}({})'.format(method, text_format.MessageToString(request, as_one_line=True)), flush=True)


# 生成された CalculatorServicer を継承し、.proto に書いた rpc を同じ名前のメソッドで実装する。
class Calculator(calc_pb2_grpc.CalculatorServicer):

    def Subtract(self, request, context):
        log('Subtract', request)
        return calc_pb2.IntReply(result=request.a - request.b)

    def Floor(self, request, context):
        log('Floor', request)
        # .proto は「double が届く」ことまでしか保証しない。NaN や無限大も double なので自分で弾く。
        if not math.isfinite(request.x):
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, 'x は有限の数にしてください')
        return calc_pb2.IntReply(result=math.floor(request.x))

    def Nroot(self, request, context):
        log('Nroot', request)
        n, x = request.n, request.x
        # abort すると、戻り値の代わりにエラーの状態コードと理由がクライアントに届く。
        if n <= 0:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, 'n は1以上にしてください')
        if x < 0 and n % 2 == 0:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, '負の数の偶数乗根は実数になりません')
        r = abs(x) ** (1 / n)
        return calc_pb2.DoubleReply(result=-r if x < 0 else r)

    def Reverse(self, request, context):
        log('Reverse', request)
        return calc_pb2.StringReply(result=request.s[::-1])

    def ValidAnagram(self, request, context):
        log('ValidAnagram', request)
        return calc_pb2.BoolReply(result=sorted(request.str1) == sorted(request.str2))

    def Sort(self, request, context):
        log('Sort', request)
        return calc_pb2.StringListReply(result=sorted(request.str_arr))


def main():
    # UNIXドメインソケットはファイルを残すので、前回の残骸を消しておく。
    try:
        os.unlink(SOCKET_PATH)
    except FileNotFoundError:
        pass

    server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
    calc_pb2_grpc.add_CalculatorServicer_to_server(Calculator(), server)
    # 本の推奨どおり AF_UNIX を使う。'127.0.0.1:50051' と書けば TCP になる。
    server.add_insecure_port('unix:' + SOCKET_PATH)
    server.start()
    print('gRPC server on unix:{} pid={}'.format(SOCKET_PATH, os.getpid()), flush=True)
    try:
        server.wait_for_termination()
    except KeyboardInterrupt:
        server.stop(grace=None)


if __name__ == '__main__':
    main()
