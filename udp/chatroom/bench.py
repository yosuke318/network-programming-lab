"""【非機能要件2】500 ルーム × 10 人 × 毎秒 2 通を捌けるかを確かめる負荷試験。

1. TCP（TCRP）で 500 ルームを作り、各ルームに 9 人ずつ参加させる（計 5000 トークン）
2. 5000 人が UDP で、それぞれ毎秒 2 通送る → サーバーは毎秒 1 万通を受け取る
3. サーバーは 1 通を同じルームの他の 9 人へ転送する → 毎秒 9 万パケットを送る
4. 受信役が実際に受け取った数を数え、到着率と毎秒のパケット数を出す

負荷をかける側が詰まらないよう、ルームを複数のプロセスに分けて動かす。

サーバーを -q 付きで起動してから実行する:
    python udp/chatroom/server.py -q
    python udp/chatroom/bench.py
"""

import argparse
import multiprocessing
import secrets
import selectors
import socket
import time

import chatpacket
import tcrp
from client import request_token


def setup_rooms(server, run_id, room_ids, members):
    """TCP でルームを作り、参加させ、UDP ソケットを用意する。"""
    clients = []   # (UDP ソケット, 送るパケット)
    hosts = []     # (UDP ソケット, ルーム名, ホストのトークン)
    for r in room_ids:
        name = 'b{}-{}'.format(run_id, r)
        tokens = []
        for i in range(members):
            operation = tcrp.OP_CREATE if i == 0 else tcrp.OP_JOIN
            token, message = request_token(server, operation, name, 'u{}'.format(i), '')
            if token is None:
                raise RuntimeError('{}: {}'.format(name, message))
            tokens.append(token)

        for i, token in enumerate(tokens):
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 256 * 1024)
            s.setblocking(False)
            s.sendto(chatpacket.encode_request(name, token), server)   # 参加の合図
            clients.append((s, chatpacket.encode_request(name, token, b'x' * 100)))
            if i == 0:
                hosts.append((s, name, token))
    return clients, hosts


def drain(sel):
    """届いているものを全部読んで捨てる（参加の知らせなど）。"""
    for key, _ in sel.select(0):
        while True:
            try:
                key.fileobj.recvfrom(chatpacket.MAX_RESPONSE_SIZE)
            except BlockingIOError:
                break


def worker(server, run_id, room_ids, members, rate, seconds, barrier, results):
    clients, hosts = setup_rooms(server, run_id, room_ids, members)
    sel = selectors.DefaultSelector()
    for s, _ in clients:
        sel.register(s, selectors.EVENT_READ)
    time.sleep(0.5)
    drain(sel)

    barrier.wait()   # 全プロセスの準備が終わってから一斉に送り始める

    n = len(clients)
    total = n * rate * seconds
    interval = 1.0 / (n * rate)
    start = next_send = time.monotonic()
    deadline = start + seconds + 2.0   # 送り終えてから 2 秒は受信を待つ
    sent = received = 0
    last = start

    while True:
        now = time.monotonic()
        if now >= deadline:
            break
        while sent < total and next_send <= now:
            s, packet = clients[sent % n]
            s.sendto(packet, server)
            sent += 1
            next_send += interval
        timeout = max(0.0, next_send - time.monotonic()) if sent < total else 0.1
        for key, _ in sel.select(timeout):
            while True:
                try:
                    key.fileobj.recvfrom(chatpacket.MAX_RESPONSE_SIZE)
                except BlockingIOError:
                    break
                received += 1
                last = time.monotonic()

    # 後片付け: ホストが退出するとルームが閉じ、トークンも消える
    for s, name, token in hosts:
        s.sendto(chatpacket.encode_request(name, token, chatpacket.LEAVE), server)
    for s, _ in clients:
        s.close()
    results.put((sent, received, last - start))


def main():
    parser = argparse.ArgumentParser(description='チャットルームの負荷試験')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=9001)
    parser.add_argument('--rooms', type=int, default=500)
    parser.add_argument('--members', type=int, default=10, help='1 ルームの人数（ホストを含む）')
    parser.add_argument('--rate', type=int, default=2, help='1 人が毎秒送るメッセージ数')
    parser.add_argument('--seconds', type=int, default=5)
    parser.add_argument('--workers', type=int, default=4, help='負荷をかける側のプロセス数')
    args = parser.parse_args()
    for name in ('rooms', 'members', 'rate', 'seconds', 'workers'):
        if getattr(args, name) <= 0:
            parser.error('--{} は 1 以上にしてください'.format(name))
    if args.members < 2:
        parser.error('--members は 2 以上にしてください（転送先がいなくなる）')

    server = (args.host, args.port)
    run_id = secrets.token_hex(3)   # 前回の試験のルームと名前がぶつからないように
    workers = min(args.workers, args.rooms)
    barrier = multiprocessing.Barrier(workers)
    results = multiprocessing.Queue()

    print('setting up {} rooms × {} members over TCP ...'.format(args.rooms, args.members), flush=True)
    procs = []
    for w in range(workers):
        room_ids = list(range(w, args.rooms, workers))
        p = multiprocessing.Process(target=worker, args=(
            server, run_id, room_ids, args.members, args.rate, args.seconds, barrier, results))
        p.start()
        procs.append(p)

    sent = received = 0
    elapsed = 0.0
    for _ in procs:
        s, r, e = results.get()
        sent += s
        received += r
        elapsed = max(elapsed, e)
    for p in procs:
        p.join()

    expected = sent * (args.members - 1)
    print('rooms × members : {} × {} = {} clients'.format(args.rooms, args.members, args.rooms * args.members))
    print('messages sent   : {} ({:.0f} msg/s to server)'.format(sent, sent / args.seconds))
    print('packets expect  : {} (each message → {} others)'.format(expected, args.members - 1))
    print('packets recv    : {} ({:.1%})'.format(received, received / expected))
    print('throughput      : {:.0f} packets/s from server'.format(received / elapsed))


if __name__ == '__main__':
    main()
