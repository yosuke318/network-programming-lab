"""【非機能要件2】毎秒 1 万パケットを転送できるかを確かめる負荷試験。

受信役のクライアントを N 人（既定 1000 人）参加させ、送信役が毎秒 R 通（既定 10 通）送る。
サーバーは 1 通を N 人に転送するので、毎秒 N × R パケットを送ることになる。
受信役が実際に受け取った数を数え、到着率と毎秒のパケット数を出す。

サーバーを -q 付きで起動してから実行する:
    python udp/chat/server.py -q
    python udp/chat/bench.py
"""

import argparse
import selectors
import socket
import time

import protocol


def main():
    parser = argparse.ArgumentParser(description='UDP チャットの負荷試験')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=9001)
    parser.add_argument('--clients', type=int, default=1000, help='受信役の人数')
    parser.add_argument('--rate', type=int, default=10, help='毎秒の送信メッセージ数')
    parser.add_argument('--seconds', type=int, default=5, help='送り続ける秒数')
    args = parser.parse_args()
    server = (args.host, args.port)

    # 受信役を参加させる（本文が空のパケット = 参加の合図）。
    sel = selectors.DefaultSelector()
    receivers = []
    for i in range(args.clients):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 256 * 1024)
        s.setblocking(False)
        s.sendto(protocol.encode('user{}'.format(i), ''), server)
        sel.register(s, selectors.EVENT_READ)
        receivers.append(s)
    time.sleep(0.5)  # サーバーが登録し終えるのを待つ

    sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    packet = protocol.encode('sender', 'x' * 100)
    total = args.rate * args.seconds
    interval = 1.0 / args.rate

    received = 0
    first = last = None
    next_send = time.monotonic()
    sent = 0
    deadline = next_send + args.seconds + 2.0  # 送り終えてから 2 秒は受信を待つ

    while time.monotonic() < deadline:
        now = time.monotonic()
        if sent < total and now >= next_send:
            sender.sendto(packet, server)
            sent += 1
            next_send += interval
        timeout = max(0.0, next_send - time.monotonic()) if sent < total else 0.1
        for key, _ in sel.select(timeout):
            while True:
                try:
                    key.fileobj.recvfrom(protocol.MAX_PACKET_SIZE)
                except BlockingIOError:
                    break
                received += 1
                last = time.monotonic()
                if first is None:
                    first = last

    expected = total * args.clients
    elapsed = (last - first) if first and last and last > first else float('nan')
    print('clients        : {}'.format(args.clients))
    print('messages sent  : {} ({} msg/s × {} s)'.format(sent, args.rate, args.seconds))
    print('packets expect : {}'.format(expected))
    print('packets recv   : {} ({:.1%})'.format(received, received / expected))
    print('throughput     : {:.0f} packets/s'.format(received / elapsed))

    for s in receivers:
        s.close()
    sender.close()


if __name__ == '__main__':
    main()
