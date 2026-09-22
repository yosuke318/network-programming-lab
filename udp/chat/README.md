# UDP チャット（課題1）

サーバーが受け取ったメッセージを、参加中の他の全クライアントへ転送する UDP のチャット。Python の標準ライブラリだけで書いている。

```
protocol.py  パケット形式 [usernamelen 1バイト][username][message]（最大 4096 バイト、UTF-8）
server.py    リレーサーバー（参加者を送信元アドレスで覚え、60 秒送信がないか 3 回連続で送信に失敗したら外す）
client.py    CLI クライアント（ユーザー名を聞いてから 1 行 = 1 メッセージで送る）
bench.py     1000 人に毎秒 10 通 = 毎秒 1 万パケットを転送できるかの負荷試験
```

コードのコメントにある【機能要件N】【非機能要件N】は課題文の番号に対応している。動かし方はリポジトリ直下の [README](../../README.md#udp-チャット) にある。

## 学習目的に対して何が学べたか

本に書かれている学習目的を項目に分け、課題1 でどこまで扱えたかを整理した。

### 主目的（サーバーの基本とバックエンドの業務）

| 本に書かれている項目 | 課題1 で学べたこと | 程度 |
|---|---|---|
| サーバー上で動くアプリの開発 | 止めるまで動き続ける `serve_forever()` のループ。Ctrl-C で抜けて、`finally` で後片付けをする流れ | ◎ |
| システムコール | `socket` / `bind` / `sendto` / `recvfrom` / `select`。これらはすべて OS へのお願いで、Python はそれを薄く包んでいるだけ。ノンブロッキングにしたときに `BlockingIOError` や `ENOBUFS` として OS から返ってくるエラーもここに入る | ○ |
| ファイル・共有メモリ・プロセススケジューリング | 触れたのは、クライアントで受信と入力待ちを別スレッドに分けたところだけ | △ |
| データベースへのアクセス | なし。`clients` はメモリにしか持っていないので、再起動すると消える。これが DB や Redis が必要になる理由の入口 | ✕ |
| Linux 環境での作業 | macOS で動かしただけ（同じ BSD ソケット API なので、コードはそのまま Linux でも動く） | △ |
| ネットワーキング | UDP はコネクションレスで、1 回の `recvfrom` = 1 メッセージ。送信元アドレスで相手を見分ける | ◎ |
| セキュリティ（暗号化・認証） | 実装はしていない。ただ、「送信元を偽装できる」「1 通受け取ると N 人に転送する増幅器になる」「名前は言ったもの勝ち」といった、認証がないと何が困るかは具体的に見えた | △ |
| スケーラビリティ | 1000 人 × 毎秒 10 通を実測し、30,000 パケット/秒まで全部届くことを確認した。1 プロセスのメモリに状態があるので台数を増やせない、という限界も見えた | ○ |

### 副次目標（TCP/UDP の内部とプロトコル）

| 本に書かれている項目 | 課題1 で学べたこと | 程度 |
|---|---|---|
| TCP/UDP の内部構造 | UDP には握手・再送・順番の保証・切断の通知がない。だから参加者の管理（`last_seen`、タイムアウト、失敗回数）をアプリが自分で書く必要があった | ○ |
| プロトコルの基本概念 | `[usernamelen 1バイト][username][message]` を自分で決め、`encode` / `decode` をサーバーとクライアントで共有した。長さを先頭に書く、上限を決める、文字コードを決める、壊れたパケットを弾く、というプロトコル設計の基本が一通り入っている | ◎ |
| 低レベルネットワーキングを自分で実装する | HTTP や WebSocket を使わず、バイト列を直接組み立てて送った | ◎ |

まとめると、しっかり身についたのは常駐サーバー・システムコールとしてのソケット・自作プロトコル・UDP の性質の 4 つで、本の副次目標のほぼ中心にあたる。主目的のうち DB、共有メモリやプロセス、暗号化と認証、Linux はまだ手つかずで、今回見えた「状態がメモリにしかない」「誰でもなりすませる」という弱点が、そのまま次に学ぶ理由になる。

## ◎ の項目の実装箇所

### ① サーバー上で動くアプリの開発（常駐と後片付け）

[server.py](server.py) の `main()`: 起動して、止まるまで動き続け、止まったら後片付けをする。

```python
server = ChatServer(args.host, args.port, args.timeout, quiet=args.quiet)  # 準備だけで、すぐ返る
try:
    server.serve_forever()           # ← ここで止まるまでずっと回る
except KeyboardInterrupt:            # Ctrl-C を受け取ったら
    print('\nshutting down (relayed {}, dropped {})'.format(server.relayed, server.dropped))
finally:
    server.close()                   # 何があってもソケットを閉じる
```

`ChatServer.serve_forever()`: 常駐の本体になっている無限ループ。

```python
last_sweep = time.monotonic()
while True:
    readable, _, _ = select.select([self.sock], [], [], SWEEP_INTERVAL)  # 来るまで、最大1秒待つ
    if readable:
        self.receive_all()                     # 来ていたら読む
    now = time.monotonic()
    if now - last_sweep >= SWEEP_INTERVAL:
        self.remove_inactive(now)              # 1秒ごとに掃除
        last_sweep = now
```

- サーバーとは「準備 → 無限ループ → 止められたら片付け」という形のプログラム。
- `select` の 1 秒は、何も来ないときに待つ上限。パケットが届けばその瞬間に返るので、転送が遅れることはない。1 秒の上限があるおかげで、誰も送ってこないときでも掃除（機能要件7）ができる。
- クライアントを常駐させているのは `for line in sys.stdin:`（キーボード入力待ち）。受信用のスレッドは `daemon=True` なので、それだけではプロセスを生かしておけない。

### ② ネットワーキング（UDP の性質）

`ChatServer.__init__()`: UDP ソケットを作って、ポートに結びつける。

```python
self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)   # DGRAM = UDP
self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
...
self.sock.setblocking(False)       # 読むものがなくても待たずに BlockingIOError を返させる
self.sock.bind((host, port))       # 0.0.0.0:9001 で待ち受ける。TCP のような listen / accept はない
```

`ChatServer.receive_all()`: 1 回の `recvfrom` で、ちょうど 1 メッセージと送信元アドレスが手に入る。

```python
while True:
    try:
        packet, addr = self.sock.recvfrom(protocol.MAX_PACKET_SIZE + 1)
    except BlockingIOError:
        return             # 届いている分を読み切った
    ...
    self.handle_packet(packet, addr)
```

`ChatServer.handle_packet()`: コネクションがないので、送信元アドレスで相手を覚える。

```python
client = self.clients.get(addr)          # addr = ('127.0.0.1', 64418)
if client is None:
    self.clients[addr] = Client(username=username, last_seen=now)   # 初めて来たら登録
else:
    client.last_seen = now               # 来るたびに「生きている」と記録
```

[client.py](client.py) の `main()`: クライアントは `bind` も `connect` もしない。

```python
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.sendto(protocol.encode(username, ''), server)   # 最初の sendto で OS が空きポートを割り当てる
```

UDP には「接続」がないので、誰が参加しているかをアプリが自分で覚えるしかない。

### ③ プロトコルの基本概念（自作の約束事）

[protocol.py](protocol.py) の定数: 約束事の上限と文字コード。

```python
MAX_PACKET_SIZE = 4096         # 1 パケットの上限
MAX_USERNAME_SIZE = 2 ** 8 - 1 # 長さを 1 バイトで書くので 255 まで
ENCODING = 'utf-8'
```

`protocol.decode()`: 受け取ったバイト列を信用せず、全部確かめてから読む。

```python
username_len = packet[0]                       # 先頭 1 バイト = 名前の長さ
if username_len == 0:
    raise ProtocolError('ユーザー名が空')
if len(packet) < 1 + username_len:             # 長さがパケットより大きいという嘘を弾く
    raise ProtocolError('usernamelen がパケットの長さより大きい')
username = packet[1:1 + username_len].decode(ENCODING)   # 壊れていたら弾く
message = packet[1 + username_len:].decode(ENCODING, errors='replace')  # 本文は壊れた部分だけ置き換える
```

プロトコルとは「どこに何バイト、何を置くか」の約束。送る側と受け取る側が同じ `protocol.py` を使うことで、約束がずれなくなる。

### ④ 低レベルネットワーキングを自分で実装する（バイト列を組み立てる）

`protocol.encode()`: HTTP も JSON も使わず、バイトを並べてパケットを作る。

```python
username_bytes = username.encode(ENCODING)    # 'alice' → b'alice'（5バイト）
message_bytes = message.encode(ENCODING)      # 'こんにちは' → 15バイト
packet = bytes([len(username_bytes)]) + username_bytes + message_bytes
#        b'\x05'                      + b'alice'       + 15バイト  = 21バイト
```

`ChatServer.relay()`: サーバーはバイト列を作り直さず、そのまま転送する。

```python
for addr, client in self.clients.items():
    if addr == sender:
        continue
    self.sock.sendto(packet, addr)     # 受け取った 21 バイトをそのまま送る
```

[client.py](client.py) の `receive_loop()`: 受け取った側も、同じ `decode` で元に戻す。

```python
packet, _ = sock.recvfrom(protocol.MAX_PACKET_SIZE)
username, message = protocol.decode(packet)    # 21バイト → ('alice', 'こんにちは')
print('\r[{}] {}'.format(username, message), flush=True)
```

ネットワークに流れているのはただのバイト列。文字列 → バイト（`encode`）→ `sendto` → `recvfrom` → バイト → 文字列（`decode`）という変換を、全部自分の手で書いている。
