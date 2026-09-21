"""ユーザーの入力を1行ずつサーバーへ送り、応答を表示するクライアント。

サーバーと同じ約束（1行 = 1メッセージ、UTF-8）で喋る。
両者が同じ区切り方を知っていることが「プロトコル」の正体。
"""

import socket
import sys

SOCKET_PATH = '/tmp/faker_socket'


def main():
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    print('connecting to {}'.format(SOCKET_PATH))

    try:
        sock.connect(SOCKET_PATH)
    except socket.error as err:
        print(err)
        sys.exit(1)

    print("コマンドを入力してください（help で一覧、quit で終了）")

    # makefile で「1行読む」単位を手に入れる。
    with sock, sock.makefile('rw', encoding='utf-8', newline='\n') as stream:
        while True:
            try:
                message = input('> ')
            except (EOFError, KeyboardInterrupt):
                print()
                break

            if not message.strip():
                continue

            stream.write(message + '\n')
            stream.flush()

            response = stream.readline()
            # 空文字列 = 相手が接続を閉じた（EOF）。
            if not response:
                print('サーバーが接続を閉じました')
                break

            print('< {}'.format(response.rstrip('\n')))

            if message.strip().lower() == 'quit':
                break

    print('closing socket')


if __name__ == '__main__':
    main()
