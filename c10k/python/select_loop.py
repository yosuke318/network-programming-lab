"""③ I/O多重化（手書き）の行エコーサーバー。

スレッドは1本だけ。selectors が OS の kqueue（Linux なら epoll）を使い、
「読める / 書けるソケット」だけを教えてもらって順に処理する。

スレッドが無いので、接続ごとの状態（読みかけのデータ、送り残し）を自分で持つ必要がある。
①②では makefile とスレッドが暗黙にやってくれていた部分。

※ ファイル名を selectors.py にすると標準ライブラリを上書きしてしまうので避けている。
"""

import os
import selectors
import socket

import work

PORT = 9102

sel = selectors.DefaultSelector()


class Conn:
    __slots__ = ('inbuf', 'outbuf')

    def __init__(self):
        self.inbuf = b''   # 改行が来るまで溜めておく受信データ
        self.outbuf = b''  # 送りきれなかった応答


def accept(lsock):
    # 1回の通知で複数の接続が待っていることがあるので、空になるまで受け取る。
    while True:
        try:
            conn, _ = lsock.accept()
        except BlockingIOError:
            return
        conn.setblocking(False)
        sel.register(conn, selectors.EVENT_READ, Conn())


def close(sock):
    sel.unregister(sock)
    sock.close()


def on_event(sock, state, mask):
    if mask & selectors.EVENT_READ:
        try:
            data = sock.recv(4096)
        except BlockingIOError:
            data = None
        except OSError:
            close(sock)
            return
        if data == b'':  # 相手が閉じた（EOF）
            close(sock)
            return
        if data:
            # 届いた分を溜め、改行が揃った行だけ応答に回す。
            state.inbuf += data
            while b'\n' in state.inbuf:
                line, _, state.inbuf = state.inbuf.partition(b'\n')
                # ここで計算している間、他の接続は誰も処理されない。
                work.burn()
                state.outbuf += line + b'\n'

    if state.outbuf:
        try:
            sent = sock.send(state.outbuf)
            state.outbuf = state.outbuf[sent:]
        except BlockingIOError:
            pass
        except OSError:
            close(sock)
            return

    # 送り残しがある時だけ「書けるようになったら教えて」と頼む。
    want = selectors.EVENT_READ | (selectors.EVENT_WRITE if state.outbuf else 0)
    if sel.get_key(sock).events != want:
        sel.modify(sock, want, state)


def main():
    lsock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    lsock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    lsock.bind(('127.0.0.1', PORT))
    lsock.listen(128)
    # ノンブロッキングにしないと accept や recv で眠ってしまい、他の接続を捌けない。
    lsock.setblocking(False)
    sel.register(lsock, selectors.EVENT_READ, None)
    print('select-loop server ({}) on 127.0.0.1:{} pid={}'.format(
        type(sel).__name__, PORT, os.getpid()), flush=True)

    while True:
        # 何か起きるまでここで眠る。1万接続あっても、返ってくるのは準備ができた分だけ。
        for key, mask in sel.select():
            if key.fileobj.fileno() == -1:  # 同じ周回の中で既に閉じたもの
                continue
            if key.data is None:
                accept(key.fileobj)
            else:
                on_event(key.fileobj, key.data, mask)


if __name__ == '__main__':
    main()
