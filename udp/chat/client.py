"""UDP チャットの CLI クライアント。

起動するとユーザー名を聞き、あとは 1 行入力するごとに 1 メッセージをサーバーへ送る。
他の人のメッセージは受信用スレッドが受け取り次第表示する。

コメントの【機能要件N】【非機能要件N】は課題文の番号に対応している。
"""

import argparse
import socket
import sys
import threading

import protocol

DEFAULT_HOST = '127.0.0.1'
DEFAULT_PORT = 9001


def ask_username():
    """【機能要件3】セッション開始時にユーザー名を入力させる。

    【機能要件4】usernamelen は 1 バイトなので、UTF-8 で 255 バイトまで。
    【機能要件5】日本語は 1 文字 3 バイトなので、文字数ではなくバイト数で確かめる。
    """
    while True:
        username = input('ユーザー名: ').strip()
        size = len(username.encode(protocol.ENCODING))
        if 1 <= size <= protocol.MAX_USERNAME_SIZE:
            return username
        print('1〜{} バイトで入力してください（今は {} バイト）'.format(
            protocol.MAX_USERNAME_SIZE, size))


def receive_loop(sock):
    """サーバーから転送されてきたメッセージを表示し続ける（受信用スレッド）。"""
    while True:
        try:
            # 【機能要件2】サーバーから届くのも最大 4096 バイトのパケット。
            packet, _ = sock.recvfrom(protocol.MAX_PACKET_SIZE)
        except OSError:
            return  # ソケットが閉じられた（終了時）

        # 【機能要件4・5】先頭 1 バイトから送信者名を取り出し、UTF-8 で読む。
        try:
            username, message = protocol.decode(packet)
        except protocol.ProtocolError:
            continue
        print('\r[{}] {}'.format(username, message), flush=True)


def main():
    parser = argparse.ArgumentParser(description='UDP チャットのクライアント')
    parser.add_argument('--host', default=DEFAULT_HOST)
    parser.add_argument('--port', type=int, default=DEFAULT_PORT)
    args = parser.parse_args()
    server = (args.host, args.port)

    username = ask_username()

    # 【機能要件1】UDP ソケットでサーバーとやり取りする。
    # 【非機能要件1】UDP には再送も到着確認もない。届かなかったメッセージは諦め、
    # 遅れて整列させるより「今のメッセージがすぐ届く」ことを優先する。
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    # 参加の合図として本文が空のパケットを送る。
    # 【機能要件6】サーバーはこれで送信元アドレスをリレー先に登録するので、
    # まだ何も発言していなくても他の人のメッセージを受け取れるようになる。
    # （最初の sendto で OS が空きポートを割り当て、以後そのポートで受信する）
    sock.sendto(protocol.encode(username, ''), server)

    threading.Thread(target=receive_loop, args=(sock,), daemon=True).start()

    print('{}:{} に {} として参加しました。Ctrl-D か Ctrl-C で終了します。'.format(
        args.host, args.port, username))
    # 【機能要件7】サーバーは一定時間送信のないクライアントを外す。
    print('しばらく発言しないとリレーから外れます。外れたら何か送れば戻れます。')

    try:
        for line in sys.stdin:
            message = line.rstrip('\n')
            if not message:
                continue  # 空の本文は参加の合図に使うので、チャットとしては送らない
            try:
                # 【機能要件2・4・5】usernamelen + username + message を UTF-8 で詰め、
                # 4096 バイトを超えるなら送らずに知らせる。
                packet = protocol.encode(username, message)
            except protocol.ProtocolError as e:
                print('送信できません: {}'.format(e))
                continue
            sock.sendto(packet, server)
    except KeyboardInterrupt:
        pass
    finally:
        sock.close()
        print('\nbye')


if __name__ == '__main__':
    main()
