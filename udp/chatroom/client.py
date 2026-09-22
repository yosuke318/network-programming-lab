"""チャットルームの CLI クライアント（ステージ 2）。

流れ:
  1. ユーザー名を入力する
  2. ルームを「作成」するか「参加」するかを選び、ルーム名（とパスワード）を入力する
  3. TCP でサーバーに TCRP のリクエストを送り、トークンを受け取って TCP を閉じる
  4. そのまま UDP でルームに入り、1 行 = 1 メッセージで送る
  5. サーバーから切断されたら 2 に戻る。Ctrl-D / Ctrl-C で退出して終わる

コメントの【機能要件1.N】【機能要件2.N】は課題文の番号に対応している。
"""

import argparse
import getpass
import os
import select
import socket
import sys
import threading
import time

import chatpacket
import tcrp

DEFAULT_HOST = '127.0.0.1'
DEFAULT_PORT = 9001   # サーバーは TCP と UDP の両方をこの番号で待っている

# サーバーに「まだいる」と伝える間隔。サーバーは 30 秒何も来ないと外す。
HEARTBEAT_INTERVAL = 5.0


class StdinLines:
    """標準入力を 1 行ずつ、待ち時間の上限つきで読む。

    input() や for line in sys.stdin は、行が来るまで止まったままで、途中で抜けられない。
    チャット中は「サーバーから切断されたら入力待ちをやめて、ルーム選択に戻る」必要があるので、
    サーバーの UDP ループと同じく select で最大 0.2 秒だけ待つ形にしている。
    （select で標準入力を待てるのは macOS / Linux。Windows では使えない）
    """

    def __init__(self):
        self.fd = sys.stdin.fileno()
        self.buffer = b''
        self.eof = False

    def readline(self, timeout=None):
        """1 行を返す。timeout 秒待っても来なければ None。入力が終わっていれば EOFError。"""
        deadline = None if timeout is None else time.monotonic() + timeout
        while b'\n' not in self.buffer:
            if self.eof:
                if not self.buffer:
                    raise EOFError
                line, self.buffer = self.buffer, b''
                return line.decode('utf-8', errors='replace')
            wait = None if deadline is None else max(0.0, deadline - time.monotonic())
            readable, _, _ = select.select([self.fd], [], [], wait)
            if not readable:
                return None
            chunk = os.read(self.fd, 4096)
            if chunk:
                self.buffer += chunk
            else:
                self.eof = True
        line, _, self.buffer = self.buffer.partition(b'\n')
        return line.decode('utf-8', errors='replace').rstrip('\r')


def prompt(lines, text):
    print(text, end='', flush=True)
    return lines.readline().strip()


def ask_password(lines, text):
    """端末ならエコーなし（getpass）、パイプなどから読むときは普通の 1 行として読む。"""
    if sys.stdin.isatty():
        return getpass.getpass(text)
    return prompt(lines, text)


def ask_username(lines):
    while True:
        username = prompt(lines, 'ユーザー名: ')
        size = len(username.encode(tcrp.ENCODING))
        if 1 <= size <= tcrp.MAX_USERNAME_SIZE:
            return username
        print('1〜{} バイトで入力してください（今は {} バイト）'.format(tcrp.MAX_USERNAME_SIZE, size))


def ask_room(lines):
    """作成か参加かと、ルーム名・パスワードを聞く。(operation, room_name, password) を返す。"""
    while True:
        choice = prompt(lines, '1) ルームを作成  2) ルームに参加  > ')
        if choice in ('1', '2'):
            break
    operation = tcrp.OP_CREATE if choice == '1' else tcrp.OP_JOIN

    while True:
        room_name = prompt(lines, 'ルーム名: ')
        size = len(room_name.encode(tcrp.ENCODING))
        # 【機能要件1.3】ルーム名は UTF-8 で 28 バイトまで
        if 1 <= size <= tcrp.MAX_ROOM_NAME_SIZE:
            break
        print('1〜{} バイトで入力してください（今は {} バイト）'.format(tcrp.MAX_ROOM_NAME_SIZE, size))

    if operation == tcrp.OP_CREATE:
        password = ask_password(lines, 'パスワード（なしなら空のまま Enter）: ')
    else:
        password = ask_password(lines, 'パスワード（なければ空のまま Enter）: ')
    return operation, room_name, password


def request_token(server, operation, room_name, username, password):
    """【機能要件1.5〜1.11】TCP で TCRP のトランザクションを 1 回行い、トークンを返す。

    失敗したら (None, 理由) を返す。成功したら (token, 説明)。
    """
    # 【機能要件1.6】State 0 のペイロード = 希望するユーザー名（とパスワード）の JSON
    body = {'username': username}
    if password:
        body['password'] = password
    try:
        request = tcrp.encode(room_name, operation, tcrp.STATE_REQUEST, tcrp.encode_json(body))
    except tcrp.ProtocolError as e:
        return None, str(e)

    # 【機能要件1.1】TCP で接続する（ここで 3 ウェイハンドシェイクが起きる）
    with socket.create_connection(server, timeout=10) as sock:
        sock.sendall(request)

        # 【機能要件1.7】State 1: ステータスコード
        _, _, state, payload = tcrp.receive(sock)
        response = tcrp.decode_json(payload)
        if state != tcrp.STATE_RESPONSE or response.get('status') != tcrp.STATUS_OK:
            return None, '{} {}'.format(response.get('status'), response.get('message'))

        # 【機能要件1.8・1.9】State 2: トークン
        _, _, state, payload = tcrp.receive(sock)
        if state != tcrp.STATE_COMPLETE:
            return None, '想定外の State {}'.format(state)
        token = payload.decode(tcrp.ENCODING)
    # 【機能要件1.11】with を抜けると TCP を閉じる（FIN が飛ぶ）
    return token, response.get('message', '')


def receive_loop(sock, stop, disconnected):
    """サーバーから届くメッセージを表示する（受信用スレッド）。

    ルームから切断されたあと、同じプロセスで別のソケットを作って入り直すことがある。
    古いスレッドが残らないよう、0.5 秒ごとに stop を確かめて自分で終わる。
    """
    sock.settimeout(0.5)
    while not stop.is_set():
        try:
            # 【機能要件2.5】サーバーから届くのは最大 4094 バイトのメッセージだけ
            data, _ = sock.recvfrom(chatpacket.MAX_RESPONSE_SIZE)
        except socket.timeout:
            continue
        except OSError:
            return
        try:
            event = chatpacket.decode_event(data)
        except chatpacket.ProtocolError:
            continue

        if event['type'] == chatpacket.TYPE_CHAT:
            print('\r[{}] {}'.format(event.get('from', '?'), event.get('text', '')), flush=True)
        elif event['type'] == chatpacket.TYPE_SYSTEM:
            print('\r* {}'.format(event.get('text', '')), flush=True)
        elif event['type'] == chatpacket.TYPE_DISCONNECT:
            # 【機能要件2.5】切断の知らせ。トークンはもうサーバーから消えているので、入り直すしかない
            print('\r!! {}'.format(event.get('text', '')), flush=True)
            disconnected.set()
            return


def heartbeat_loop(sock, server, packet, stop):
    """一定間隔で空のメッセージを送り、発言しなくてもリレーから外れないようにする。"""
    while not stop.wait(HEARTBEAT_INTERVAL):
        try:
            sock.sendto(packet, server)
        except OSError:
            return


def chat(lines, server, room_name, token):
    """【機能要件2】UDP でルームに入って会話する。

    戻り値: 'quit'（自分で抜けた） / 'disconnected'（サーバーから切断された）
    """
    # 【機能要件2.3】ここからのやり取りはすべて UDP
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    stop = threading.Event()
    disconnected = threading.Event()
    heartbeat = chatpacket.encode_request(room_name, token, chatpacket.HEARTBEAT)

    # 【機能要件1.10】最初の UDP パケットで、このアドレスがトークンの所有者になる。
    sock.sendto(heartbeat, server)

    threads = [
        threading.Thread(target=receive_loop, args=(sock, stop, disconnected), daemon=True),
        threading.Thread(target=heartbeat_loop, args=(sock, server, heartbeat, stop), daemon=True),
    ]
    for t in threads:
        t.start()

    print('ルーム {} に入りました。Ctrl-D か Ctrl-C で退出します。'.format(room_name))
    result = 'quit'
    try:
        while True:
            if disconnected.is_set():
                result = 'disconnected'
                break
            line = lines.readline(timeout=0.2)
            if not line:
                continue  # 時間切れ（None）か空行
            try:
                # 【機能要件2.4・2.5】RoomNameSize | TokenSize | RoomName | Token | Message（最大 4096）
                packet = chatpacket.encode_request(room_name, token, line.encode(chatpacket.ENCODING))
            except chatpacket.ProtocolError as e:
                print('送信できません: {}'.format(e))
                continue
            sock.sendto(packet, server)
    except (EOFError, KeyboardInterrupt):
        pass
    finally:
        if result == 'quit':
            # 自分から抜けることをサーバーに伝える。ホストなら、これでルームが閉じる（【機能要件2.1】）
            try:
                sock.sendto(chatpacket.encode_request(room_name, token, chatpacket.LEAVE), server)
            except OSError:
                pass
        stop.set()
        for t in threads:
            t.join()
        sock.close()
    return result


def main():
    parser = argparse.ArgumentParser(description='チャットルームのクライアント')
    parser.add_argument('--host', default=DEFAULT_HOST)
    parser.add_argument('--port', type=int, default=DEFAULT_PORT)
    args = parser.parse_args()
    server = (args.host, args.port)

    lines = StdinLines()
    try:
        username = ask_username(lines)
        while True:
            operation, room_name, password = ask_room(lines)
            try:
                token, message = request_token(server, operation, room_name, username, password)
            except (OSError, tcrp.ProtocolError) as e:
                print('サーバーに接続できません: {}'.format(e))
                continue
            if token is None:
                print('失敗しました: {}'.format(message))
                continue
            print(message)

            if chat(lines, server, room_name, token) == 'quit':
                break
            print('もう一度ルームを選んでください。')
    except (EOFError, KeyboardInterrupt):
        pass
    print('\nbye')


if __name__ == '__main__':
    main()
