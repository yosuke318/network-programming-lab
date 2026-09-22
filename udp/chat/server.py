"""UDP チャットのリレーサーバー。

受け取ったメッセージを、いま接続中の他の全クライアントへそのまま転送する。
UDP にはコネクションがないので「接続中」はサーバーが自分で覚えておく必要がある。
ここでは「最近パケットを送ってきた送信元アドレス」を接続中とみなす。

コメントの【機能要件N】【非機能要件N】は課題文の番号に対応している。
"""

import argparse
import errno
import select
import socket
import time
from dataclasses import dataclass

import protocol

DEFAULT_HOST = '0.0.0.0'
DEFAULT_PORT = 9001

# 【機能要件7】しばらく何も送ってこないクライアントは外す。その「しばらく」の秒数。
DEFAULT_TIMEOUT = 60.0
# 【機能要件7】転送が連続でこの回数失敗したクライアントは外す。
MAX_CONSECUTIVE_FAILURES = 3
# タイムアウト切れのクライアントを探す間隔（秒）。
SWEEP_INTERVAL = 1.0

# 【非機能要件2】1000 人 × 毎秒 10 メッセージの転送が一瞬重なっても溢れにくいよう、
# カーネルの送受信バッファを大きめにとる（OS の上限で小さくされることはある）。
SOCKET_BUFFER_SIZE = 4 * 1024 * 1024


@dataclass
class Client:
    """【機能要件6・7】リレー先 1 人ぶんの情報。メモリ上にだけ持つ。"""
    username: str
    last_seen: float        # 最後にパケットを受け取った時刻（time.monotonic）
    failures: int = 0       # 連続で転送に失敗した回数


class ChatServer:
    def __init__(self, host, port, timeout, quiet=False):
        self.timeout = timeout
        self.quiet = quiet

        # 【機能要件6】リレーシステム。送信元アドレス (ip, port) → Client。
        # サーバーを止めれば消える一時的な記録で、ファイルや DB には残さない。
        self.clients = {}

        # 【機能要件1】UDP ソケット（SOCK_DGRAM）で待ち受ける。
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        for option in (socket.SO_RCVBUF, socket.SO_SNDBUF):
            try:
                self.sock.setsockopt(socket.SOL_SOCKET, option, SOCKET_BUFFER_SIZE)
            except OSError:
                pass
        # 【非機能要件1】ノンブロッキングにして、送信バッファが詰まっても待たずに捨てる。
        # 遅れて届く古いメッセージより、次の新しいメッセージを優先する。
        self.sock.setblocking(False)
        self.sock.bind((host, port))

        self.relayed = 0    # 転送できたパケット数
        self.dropped = 0    # 送信バッファが詰まって捨てたパケット数

    def log(self, text):
        if not self.quiet:
            print(text, flush=True)

    def serve_forever(self):
        """メインループ。

        【非機能要件2】スレッドを使わず 1 本のループで受信・転送・掃除をする。
        clients をロックする必要がなく、Python でも毎秒 1 万パケット程度は捌ける。
        """
        host, port = self.sock.getsockname()
        print('UDP chat server listening on {}:{} (timeout {}s)'.format(
            host, port, self.timeout), flush=True)

        last_sweep = time.monotonic()
        while True:
            # 受信できるパケットが来るか、掃除の時間になるまで待つ。
            readable, _, _ = select.select([self.sock], [], [], SWEEP_INTERVAL)
            if readable:
                self.receive_all()

            now = time.monotonic()
            if now - last_sweep >= SWEEP_INTERVAL:
                self.remove_inactive(now)
                last_sweep = now

    def receive_all(self):
        """いま届いているパケットをすべて読んで処理する。"""
        while True:
            try:
                # 【機能要件2】4096 バイトを超えたパケットを見分けるため 1 バイト多く読む。
                # （ちょうど 4096 で読むと、長すぎるパケットが黙って切り詰められてしまう）
                packet, addr = self.sock.recvfrom(protocol.MAX_PACKET_SIZE + 1)
            except BlockingIOError:
                return  # 読み切った
            except OSError as e:
                # UDP では前に送った相手の ICMP エラーがここで出ることがある。無視して続ける。
                self.log('recvfrom error: {}'.format(e))
                continue
            self.handle_packet(packet, addr)

    def handle_packet(self, packet, addr):
        # 【機能要件2】4096 バイトを超えるメッセージは処理しない。
        if len(packet) > protocol.MAX_PACKET_SIZE:
            self.log('drop: {} から {} バイト超のパケット'.format(addr, protocol.MAX_PACKET_SIZE))
            return

        # 【機能要件4・5】先頭 1 バイトの usernamelen からユーザー名と本文を取り出す。
        try:
            username, message = protocol.decode(packet)
        except protocol.ProtocolError as e:
            self.log('drop: {} から不正なパケット ({})'.format(addr, e))
            return

        # 【機能要件6・7】送ってきたクライアントをリレー先に登録し、最終送信時刻を更新する。
        # UDP はコネクションレスなので、これが「接続している」ことの唯一の手がかりになる。
        now = time.monotonic()
        client = self.clients.get(addr)
        if client is None:
            self.clients[addr] = Client(username=username, last_seen=now)
            self.log('+ {} joined from {}:{} (clients: {})'.format(
                username, addr[0], addr[1], len(self.clients)))
        else:
            client.username = username
            client.last_seen = now
            client.failures = 0

        # 本文が空のパケットは参加の合図（クライアント起動時に送られる）なので転送しない。
        if not message:
            return

        self.log('[{}] {}'.format(username, message))
        self.relay(packet, sender=addr)

    def relay(self, packet, sender):
        """【機能要件6】受け取ったパケットを送信者以外の全クライアントへ転送する。

        パケットは usernamelen + username + message の形のまま転送するので、
        受け取ったクライアントも同じ decode で送信者名を取り出せる。
        【非機能要件2】作り直さず同じ bytes を sendto するだけにして 1 件あたりの手間を減らす。
        """
        removed = []
        for addr, client in self.clients.items():
            if addr == sender:
                continue
            try:
                self.sock.sendto(packet, addr)
            except BlockingIOError:
                # 【非機能要件1】送信バッファが一杯。待たずにこの 1 通は諦める。
                # サーバー側の混雑でありクライアントのせいではないので失敗回数には数えない。
                self.dropped += 1
                continue
            except OSError as e:
                if e.errno == errno.ENOBUFS:  # macOS はバッファ不足をこのエラーで返す
                    self.dropped += 1
                    continue
                # 【機能要件7】宛先に届けられなかった。連続失敗が続いたら外す。
                client.failures += 1
                self.log('send to {} failed ({}/{}): {}'.format(
                    client.username, client.failures, MAX_CONSECUTIVE_FAILURES, e))
                if client.failures >= MAX_CONSECUTIVE_FAILURES:
                    removed.append(addr)
                continue
            client.failures = 0
            self.relayed += 1

        for addr in removed:
            client = self.clients.pop(addr)
            self.log('- {} removed: {} 回連続で送信失敗 (clients: {})'.format(
                client.username, MAX_CONSECUTIVE_FAILURES, len(self.clients)))

    def remove_inactive(self, now):
        """【機能要件7】最後の送信から timeout 秒たったクライアントをリレー先から外す。"""
        expired = [addr for addr, client in self.clients.items()
                   if now - client.last_seen > self.timeout]
        for addr in expired:
            client = self.clients.pop(addr)
            self.log('- {} removed: {:.0f} 秒間送信なし (clients: {})'.format(
                client.username, self.timeout, len(self.clients)))

    def close(self):
        self.sock.close()


def main():
    parser = argparse.ArgumentParser(description='UDP チャットのリレーサーバー')
    parser.add_argument('--host', default=DEFAULT_HOST)
    parser.add_argument('--port', type=int, default=DEFAULT_PORT)
    parser.add_argument('--timeout', type=float, default=DEFAULT_TIMEOUT,
                        help='この秒数送信のないクライアントを外す（既定 %(default)s）')
    parser.add_argument('-q', '--quiet', action='store_true',
                        help='メッセージごとのログを出さない（負荷試験用）')
    args = parser.parse_args()

    # 【機能要件（前提）】サーバーは CLI で起動し、止めるまで待ち受け続ける。
    # サーバーが止まっていればチャットサービスそのものが停止している。
    server = ChatServer(args.host, args.port, args.timeout, quiet=args.quiet)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nshutting down (relayed {}, dropped {})'.format(server.relayed, server.dropped))
    finally:
        server.close()


if __name__ == '__main__':
    main()
