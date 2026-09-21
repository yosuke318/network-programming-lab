"""② 1接続1スレッドの行エコーサーバー。

接続ごとにOSスレッドを1本作る。書き方は①とほぼ同じで、並行に捌ける。
ただしスレッドはメモリを食い、OSの上限（macOS は1プロセス4096本）で頭打ちになる。
"""

import os
import socket
import threading

PORT = 9101


def handle(conn):
    try:
        with conn, conn.makefile('rwb') as stream:
            for line in stream:
                stream.write(line)
                stream.flush()
    except OSError:
        pass


def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(('127.0.0.1', PORT))
    sock.listen(128)
    print('threads server on 127.0.0.1:{} pid={}'.format(PORT, os.getpid()), flush=True)

    failed = 0
    while True:
        conn, _ = sock.accept()
        try:
            threading.Thread(target=handle, args=(conn,), daemon=True).start()
        except RuntimeError as err:
            # OSがこれ以上スレッドを作らせてくれない。これが C10K の壁。
            failed += 1
            if failed == 1 or failed % 1000 == 0:
                print('thread creation failed x{}: {} (active threads={})'.format(
                    failed, err, threading.active_count()), flush=True)
            conn.close()


if __name__ == '__main__':
    main()
