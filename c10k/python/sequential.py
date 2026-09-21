"""① 直列。従来の書き方（書籍のサーバーと同じ構造）の行エコーサーバー。

accept → 処理 → accept の順に回るので、1人目が繋がっている間は2人目を処理できない。
"""

import os
import socket

import work

PORT = 9100


def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(('127.0.0.1', PORT))
    sock.listen(128)
    print('sequential server on 127.0.0.1:{} pid={}'.format(PORT, os.getpid()), flush=True)

    while True:
        conn, _ = sock.accept()
        try:
            with conn, conn.makefile('rwb') as stream:
                for line in stream:
                    work.burn()
                    stream.write(line)
                    stream.flush()
        except OSError:
            pass


if __name__ == '__main__':
    main()
