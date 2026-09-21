"""クライアントからのコマンドを受け取り、faker で作った偽データを返すサーバー。

プロトコル: 1行 = 1メッセージ（改行区切り、UTF-8）。
ストリームソケットには境界がないので、区切りは自分で決める必要がある。
ここでは「改行まで」を1メッセージとする約束にした。
"""

import os
import socket

from faker import Faker

SOCKET_PATH = '/tmp/faker_socket'

fake = Faker('ja_JP')

# 使えるコマンドと、それに対応する faker の生成関数。
COMMANDS = {
    'name': fake.name,
    'address': fake.address,
    'email': fake.email,
    'company': fake.company,
    'text': fake.text,
    'profile': lambda: '{} / {} / {}'.format(fake.name(), fake.email(), fake.company()),
}


def make_response(message):
    """受け取った1行に対する応答を作る。"""
    key = message.strip().lower()
    if key == 'help':
        return 'コマンド一覧: ' + ', '.join(sorted(COMMANDS)) + ', help, quit'
    if key in COMMANDS:
        return COMMANDS[key]()
    return '未知のコマンド {!r}。help で一覧を表示します。'.format(message.strip())


def sanitize(text):
    """改行区切りプロトコルなので、本文に改行を含められない。

    faker の address() や text() は改行を含むため、そのまま流すと
    1つの応答が複数メッセージに見えてしまう。ここで潰しておく。
    """
    return text.replace('\r\n', ' / ').replace('\n', ' / ')


def serve(connection):
    # makefile はバラバラに届くバイト列を溜めて「1行」単位で読ませてくれる。
    # Go の bufio.Reader と同じ役割。
    with connection.makefile('rw', encoding='utf-8', newline='\n') as stream:
        for line in stream:
            message = line.rstrip('\n')
            print('Received: {!r}'.format(message))

            if message.strip().lower() == 'quit':
                stream.write('さようなら\n')
                stream.flush()
                return

            response = sanitize(make_response(message))
            print('Sending : {!r}'.format(response))
            stream.write(response + '\n')
            stream.flush()


def main():
    # UNIXドメインソケットはファイルを残すので、bind する前に残骸を消す。
    try:
        os.unlink(SOCKET_PATH)
    except FileNotFoundError:
        pass

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.bind(SOCKET_PATH)
    sock.listen(1)
    print('Starting up on {}'.format(SOCKET_PATH))

    try:
        while True:
            connection, _ = sock.accept()
            print('--- connection opened ---')
            try:
                serve(connection)
            finally:
                print('--- connection closed ---')
                connection.close()
    except KeyboardInterrupt:
        print('\nshutting down')
    finally:
        sock.close()
        try:
            os.unlink(SOCKET_PATH)
        except FileNotFoundError:
            pass


if __name__ == '__main__':
    main()
