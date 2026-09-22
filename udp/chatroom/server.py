"""チャットルームのサーバー（ステージ 2）。

同じポート番号で TCP と UDP の両方を待ち受ける（TCP と UDP はポート番号の空間が別なので、
同じ 9001 番を両方で使える）。

- TCP（TCRP）: ルームの作成・参加を受け付け、トークンを発行して接続を閉じる
- UDP        : トークンを持ったクライアントのメッセージを、同じルームの他の全員へ転送する

TCP の受け付けは接続ごとにスレッドで処理し、UDP は 1 本のループで処理する。
両方から触る rooms は self.lock で守る。

コメントの【機能要件1.N】【機能要件2.N】【非機能要件N】は課題文の番号に対応している。
（課題文で 2 つ目の節も「1.」と書かれているので、UDP 側を 2 と読み替えている）
"""

import argparse
import errno
import hashlib
import hmac
import os
import secrets
import select
import socket
import threading
import time
from dataclasses import dataclass, field

import chatpacket
import tcrp

DEFAULT_HOST = '0.0.0.0'
DEFAULT_PORT = 9001

# ステージ 1 の【機能要件7】: しばらく何も送ってこないクライアントは外す。
# クライアントは 5 秒ごとに生存確認（空のパケット）を送るので、発言しなくても外れない。
# 外れるのは、クライアントが落ちたり回線が切れたりして生存確認が途絶えたとき。
DEFAULT_TIMEOUT = 30.0
MAX_CONSECUTIVE_FAILURES = 3
SWEEP_INTERVAL = 1.0

# TCRP のやり取りで相手が黙ったままのとき、何秒で諦めるか。
TCP_TIMEOUT = 5.0

# パスワードはそのまま持たず、塩（salt）を混ぜて何度もハッシュした値だけを持つ。
PASSWORD_HASH_ITERATIONS = 100_000

# 【非機能要件2】500 ルーム × 10 人 × 毎秒 2 通 = 毎秒 1 万通を受け、9 万パケットを転送する。
# 一瞬の集中で溢れにくいよう、カーネルの送受信バッファを大きめにとる。
SOCKET_BUFFER_SIZE = 8 * 1024 * 1024


@dataclass
class Member:
    """【機能要件1.10】許可リストに載っているトークン 1 つぶんの情報。"""
    token: str
    username: str
    ip: str                 # TCP でトークンを受け取ったときの IP。UDP の送信元と一致しなければ弾く
    is_host: bool
    last_seen: float        # 最後に UDP パケットを受け取った時刻（発行直後は発行時刻）
    addr: tuple = None      # UDP の (ip, port)。最初の UDP パケットで決まる（= トークンの所有者）
    failures: int = 0


@dataclass
class Room:
    name: str
    host_token: str
    password_salt: bytes = None     # パスワードなしのルームは None
    password_hash: bytes = None
    # 【機能要件1.10】このルームの許可リスト。トークン → Member
    members: dict = field(default_factory=dict)


def hash_password(password, salt):
    return hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, PASSWORD_HASH_ITERATIONS)


class ChatRoomServer:
    def __init__(self, host, port, timeout, quiet=False):
        self.timeout = timeout
        self.quiet = quiet

        # ルーム名 → Room。メモリ上にだけ持つ。
        self.rooms = {}
        # TCP のスレッドと UDP のループが同時に rooms を書き換えないようにする鍵。
        self.lock = threading.Lock()

        # 【機能要件1.1】ルームの作成・参加用の TCP ソケット
        self.tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.tcp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.tcp_sock.bind((host, port))
        self.tcp_sock.listen(128)

        # 【機能要件2.3】チャット用の UDP ソケット（TCP と同じポート番号）
        self.udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        for option in (socket.SO_RCVBUF, socket.SO_SNDBUF):
            try:
                self.udp_sock.setsockopt(socket.SOL_SOCKET, option, SOCKET_BUFFER_SIZE)
            except OSError:
                pass
        # 【非機能要件1】ノンブロッキングにして、送信バッファが詰まっても待たずに捨てる。
        self.udp_sock.setblocking(False)
        self.udp_sock.bind((host, port))

        self.relayed = 0
        self.dropped = 0

    def log(self, text):
        if not self.quiet:
            print(text, flush=True)

    def serve_forever(self):
        host, port = self.udp_sock.getsockname()
        print('chat room server listening on {}:{} (TCP + UDP, timeout {}s)'.format(
            host, port, self.timeout), flush=True)
        threading.Thread(target=self.accept_loop, daemon=True).start()
        self.udp_loop()

    # ======================================================================
    # TCP: ルームの作成と参加（TCRP）
    # ======================================================================

    def accept_loop(self):
        """TCP の接続を受け付け、1 接続ごとにスレッドを立てて処理する。

        TCRP のやり取りは 1 往復半で終わる短いものなので、スレッドで十分。
        相手が遅くても UDP のループが止まらないよう、UDP とは別のスレッドにしている。
        """
        while True:
            try:
                conn, addr = self.tcp_sock.accept()
            except OSError:
                return  # サーバー終了でソケットが閉じられた
            threading.Thread(target=self.handle_tcp, args=(conn, addr), daemon=True).start()

    def handle_tcp(self, conn, addr):
        """【機能要件1.5〜1.8・1.11】1 回の TCRP トランザクションを処理して TCP を閉じる。"""
        conn.settimeout(TCP_TIMEOUT)
        try:
            # State 0: クライアントからのリクエストを読む
            room_name, operation, state, payload = tcrp.receive(conn)
            status, message, token = self.process_request(room_name, operation, state, payload, addr[0])

            # 【機能要件1.7】State 1: ステータスコードをすぐに返す
            response = tcrp.encode_json({'status': status, 'message': message})
            conn.sendall(tcrp.encode(room_name, operation, tcrp.STATE_RESPONSE, response))

            # 【機能要件1.8・1.9】State 2: 成功したときだけトークンを渡して完了
            if token is not None:
                conn.sendall(tcrp.encode(room_name, operation, tcrp.STATE_COMPLETE,
                                         token.encode(tcrp.ENCODING)))
        except (tcrp.ProtocolError, OSError) as e:
            self.log('TCRP error from {}:{}: {}'.format(addr[0], addr[1], e))
        finally:
            # 【機能要件1.11】作成・参加が終わったら TCP は閉じる。以後は UDP だけ。
            conn.close()

    def process_request(self, room_name, operation, state, payload, ip):
        """リクエストを処理し、(ステータスコード, 説明, トークン or None) を返す。"""
        if state != tcrp.STATE_REQUEST:
            return tcrp.STATUS_BAD_REQUEST, 'State は 0（リクエスト）にしてください', None
        if operation not in (tcrp.OP_CREATE, tcrp.OP_JOIN):
            return tcrp.STATUS_BAD_REQUEST, '未知の Operation {}'.format(operation), None
        if not room_name:
            return tcrp.STATUS_BAD_REQUEST, 'ルーム名が空です', None

        # 【機能要件1.6】ペイロードには希望するユーザー名（と、あればパスワード）が入っている
        try:
            body = tcrp.decode_json(payload)
        except tcrp.ProtocolError as e:
            return tcrp.STATUS_BAD_REQUEST, str(e), None
        username = body.get('username')
        password = body.get('password') or ''
        if not isinstance(username, str) or not username.strip():
            return tcrp.STATUS_BAD_REQUEST, 'ユーザー名が空です', None
        if not isinstance(password, str):
            return tcrp.STATUS_BAD_REQUEST, 'パスワードは文字列にしてください', None
        username = username.strip()
        if len(username.encode(tcrp.ENCODING)) > tcrp.MAX_USERNAME_SIZE:
            return tcrp.STATUS_BAD_REQUEST, 'ユーザー名は {} バイトまでです'.format(tcrp.MAX_USERNAME_SIZE), None

        if operation == tcrp.OP_CREATE:
            return self.create_room(room_name, username, password, ip)
        return self.join_room(room_name, username, password, ip)

    def create_room(self, room_name, username, password, ip):
        """【機能要件1.5〜1.8】ルームを作り、作った人をホストとしてトークンを発行する。"""
        # パスワードのハッシュ計算は重い（数十ミリ秒）ので、鍵を持つ前に済ませる。
        # 鍵を持ったまま計算すると、その間 UDP の転送が止まってしまう。
        salt = password_hash = None
        if password:
            salt = os.urandom(16)
            password_hash = hash_password(password, salt)

        with self.lock:
            if room_name in self.rooms:
                return tcrp.STATUS_CONFLICT, 'ルーム {} はすでにあります'.format(room_name), None
            # 【機能要件1.8】ユニークなトークンを作り、このユーザー名を割り当てる。
            # このトークンがホストの目印になる。
            token = self.new_token()
            room = Room(name=room_name, host_token=token,
                        password_salt=salt, password_hash=password_hash)
            room.members[token] = Member(token=token, username=username, ip=ip,
                                         is_host=True, last_seen=time.monotonic())
            self.rooms[room_name] = room

        self.log('* room {!r} created by {} ({}){}'.format(
            room_name, username, ip, ' [password]' if password else ''))
        return tcrp.STATUS_OK, 'ルーム {} を作成しました'.format(room_name), token

    def join_room(self, room_name, username, password, ip):
        """【機能要件1.9】既存のルームに参加するトークンを発行する（ホストではない）。"""
        with self.lock:
            room = self.rooms.get(room_name)
            if room is None:
                return tcrp.STATUS_ROOM_NOT_FOUND, 'ルーム {} はありません'.format(room_name), None
            salt, expected = room.password_salt, room.password_hash

        # パスワード付きのルームは、正しいパスワードでないと参加できない。
        # ハッシュの計算は重いので、ここでも鍵を持たずに行う。
        if expected is not None:
            # hmac.compare_digest は、どこまで一致したかで処理時間が変わらない比較。
            # 普通の == だと、時間の差からパスワードを推測される余地がある。
            if not hmac.compare_digest(hash_password(password, salt), expected):
                return tcrp.STATUS_WRONG_PASSWORD, 'パスワードが違います', None

        with self.lock:
            # 鍵を手放している間にルームが閉じられていないか確かめ直す。
            if self.rooms.get(room_name) is not room:
                return tcrp.STATUS_ROOM_NOT_FOUND, 'ルーム {} はありません'.format(room_name), None
            if any(m.username == username for m in room.members.values()):
                return tcrp.STATUS_CONFLICT, 'ユーザー名 {} はこのルームで使われています'.format(username), None
            token = self.new_token()
            room.members[token] = Member(token=token, username=username, ip=ip,
                                         is_host=False, last_seen=time.monotonic())

        self.log('* {} ({}) got a token for room {!r}'.format(username, ip, room_name))
        return tcrp.STATUS_OK, 'ルーム {} に参加できます'.format(room_name), token

    @staticmethod
    def new_token():
        # secrets は推測されにくい乱数を作る（random モジュールは推測できるので使わない）。
        # 24 バイトの乱数 → 32 文字。上限の 255 バイト（【機能要件1.8】）に十分収まる。
        return secrets.token_urlsafe(24)

    # ======================================================================
    # UDP: ルーム内のチャット
    # ======================================================================

    def udp_loop(self):
        """【非機能要件2】受信・転送・掃除を 1 本のループで行う（ステージ 1 と同じ形）。"""
        last_sweep = time.monotonic()
        while True:
            readable, _, _ = select.select([self.udp_sock], [], [], SWEEP_INTERVAL)
            if readable:
                self.receive_all()
            now = time.monotonic()
            if now - last_sweep >= SWEEP_INTERVAL:
                with self.lock:
                    self.remove_inactive(now)
                last_sweep = now

    def receive_all(self):
        while True:
            try:
                # 【機能要件2.4】4096 バイトを超えるパケットを見分けるため 1 バイト多く読む。
                packet, addr = self.udp_sock.recvfrom(chatpacket.MAX_REQUEST_SIZE + 1)
            except BlockingIOError:
                return
            except OSError as e:
                self.log('recvfrom error: {}'.format(e))
                continue
            try:
                room_name, token, message = chatpacket.decode_request(packet)
            except chatpacket.ProtocolError as e:
                self.log('drop: {} から不正なパケット ({})'.format(addr, e))
                continue
            with self.lock:
                self.handle_packet(room_name, token, message, addr)

    def handle_packet(self, room_name, token, message, addr):
        """1 つの UDP パケットを処理する。self.lock を持った状態で呼ぶ。"""
        # 【機能要件2.2】ルームに入るには、そのルームの許可リストにあるトークンが要る。
        room = self.rooms.get(room_name)
        member = room.members.get(token) if room else None
        if member is None:
            self.log('drop: {} のトークンは {!r} の許可リストにない'.format(addr, room_name))
            return

        # 【機能要件1.10・2.2】トークンを受け取ったときの IP と、送信元の IP が一致しなければ弾く。
        # トークンを盗み見た別のマシンからは使えない。
        if addr[0] != member.ip:
            self.log('drop: {} は {} のトークンだが IP が違う ({})'.format(
                addr, member.username, member.ip))
            return

        member.last_seen = time.monotonic()
        member.failures = 0

        # 【機能要件1.10】最初にこのトークンで UDP を送ってきたアドレスを、トークンの所有者にする。
        if member.addr is None:
            member.addr = addr
        elif addr != member.addr:
            self.log('drop: {} は {} のトークンだが UDP の送信元が変わった（元 {}）'.format(
                addr, member.username, member.addr))
            return

        if message == chatpacket.LEAVE:
            # 自分から抜けたので、本人に切断の知らせは送らない。
            self.remove_member(room, member, notice=None)
            return

        if first_time:
            self.log('+ {} joined {!r} from {}:{}{}'.format(
                member.username, room.name, addr[0], addr[1], ' (host)' if member.is_host else ''))
            self.broadcast(room, chatpacket.encode_event(
                chatpacket.TYPE_SYSTEM, '{} が参加しました'.format(member.username)), exclude=token)

        if message == chatpacket.HEARTBEAT:
            return  # 参加の合図 / 生存確認。last_seen を更新したので、これで終わり

        # 【機能要件2.5】サーバーからは「メッセージだけ」を送る。
        # 誰の発言かがわかるよう、ユーザー名を JSON の中に入れる。
        # 【非機能要件2】JSON を作るのは 1 通につき 1 回だけ。全員に同じ bytes を送る。
        text = message.decode(chatpacket.ENCODING, errors='replace')
        if not self.quiet:  # 毎秒 1 万通のときに文字列を組み立てる手間も省く
            self.log('[{}] {}: {}'.format(room.name, member.username, text))
        data = chatpacket.encode_event(chatpacket.TYPE_CHAT, text, sender=member.username)
        self.broadcast(room, data, exclude=token)

    def broadcast(self, room, data, exclude=None):
        """ルームの他の全員へ転送する。連続で送信に失敗した人は外す。"""
        failed = []
        for member in room.members.values():
            if member.token == exclude or member.addr is None:
                continue  # 本人と、まだ UDP で来ていない人には送らない
            result = self.send(member, data)
            if result is False:
                member.failures += 1
                if member.failures >= MAX_CONSECUTIVE_FAILURES:
                    failed.append(member)
            elif result is True:
                member.failures = 0

        for member in failed:
            if room.members.get(member.token) is member:
                self.remove_member(room, member,
                                   notice='{} 回連続で送信に失敗したため切断しました'.format(
                                       MAX_CONSECUTIVE_FAILURES))

    def send(self, member, data):
        """1 人に送る。成功 True、宛先の問題で失敗 False、サーバーの混雑で捨てた None。"""
        try:
            self.udp_sock.sendto(data, member.addr)
        except BlockingIOError:
            # 【非機能要件1】送信バッファが一杯。待たずに捨てる（失敗回数には数えない）。
            self.dropped += 1
            return None
        except OSError as e:
            if e.errno == errno.ENOBUFS:
                self.dropped += 1
                return None
            self.log('send to {} failed: {}'.format(member.username, e))
            return False
        self.relayed += 1
        return True

    def remove_member(self, room, member, notice):
        """リレーから外し、トークンも許可リストから消す。self.lock を持った状態で呼ぶ。

        【機能要件2.5】外されたクライアントには切断の知らせ（notice）を送る。
        クライアントは TCP でもう一度参加し直す必要がある。
        """
        del room.members[member.token]
        if notice and member.addr is not None:
            self.send(member, chatpacket.encode_event(chatpacket.TYPE_DISCONNECT, notice))
        self.log('- {} left {!r}{}'.format(member.username, room.name,
                                            ' ({})'.format(notice) if notice else ''))

        # 【機能要件2.1】ホストが抜けたら、ルームを閉じる。
        if member.is_host:
            self.close_room(room, 'ホストの {} が退出したため、ルーム {} は閉じられました'.format(
                member.username, room.name))
        else:
            self.broadcast(room, chatpacket.encode_event(
                chatpacket.TYPE_SYSTEM, '{} が退出しました'.format(member.username)))

    def close_room(self, room, notice):
        """【機能要件2.1】ルームを消し、残っている全員に切断を知らせてトークンも消す。"""
        del self.rooms[room.name]
        data = chatpacket.encode_event(chatpacket.TYPE_DISCONNECT, notice)
        for member in room.members.values():
            if member.addr is not None:
                self.send(member, data)
        room.members.clear()
        self.log('* room {!r} closed'.format(room.name))

    def remove_inactive(self, now):
        """timeout 秒 UDP で何も送ってこない人を外す。self.lock を持った状態で呼ぶ。

        トークンを受け取ったのに UDP で一度も来ない人も、発行時刻から数えて同じように外す。
        そうしないと、使われないトークンが許可リストに残り続ける。
        """
        for room in list(self.rooms.values()):
            for member in list(room.members.values()):
                if self.rooms.get(room.name) is not room:
                    break  # ホストが外れてルームが閉じた
                if now - member.last_seen > self.timeout:
                    self.remove_member(room, member,
                                       notice='{:.0f} 秒間送信がなかったため切断しました'.format(self.timeout))

    def close(self):
        self.tcp_sock.close()
        self.udp_sock.close()


def main():
    parser = argparse.ArgumentParser(description='チャットルームのサーバー（TCP + UDP）')
    parser.add_argument('--host', default=DEFAULT_HOST)
    parser.add_argument('--port', type=int, default=DEFAULT_PORT)
    parser.add_argument('--timeout', type=float, default=DEFAULT_TIMEOUT,
                        help='この秒数 UDP で何も送ってこないクライアントを外す（既定 %(default)s）')
    parser.add_argument('-q', '--quiet', action='store_true',
                        help='メッセージごとのログを出さない（負荷試験用）')
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error('--timeout は 0 より大きくしてください')

    server = ChatRoomServer(args.host, args.port, args.timeout, quiet=args.quiet)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nshutting down (relayed {}, dropped {})'.format(server.relayed, server.dropped))
    finally:
        server.close()


if __name__ == '__main__':
    main()
