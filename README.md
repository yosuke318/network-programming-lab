# network-programming-lab

ソケット通信からHTTPまで、ネットワークプログラミングを手を動かして学ぶための実験リポジトリ。

同じ題材を Go と Python の両方で書き、生のバイト列がどう流れるかを観察できるようにしている。

## 構成

```
tcp/    TCPソケット
  server/       受信バイトを16進ダンプして大文字で返すエコーサーバー
  client/       任意のアドレスに繋いで標準入力を送る生クライアント
  no-accept/    accept() を呼ばないサーバー（ハンドシェイクはカーネルがやることの確認用）

http/   HTTP
  server/       net/http による比較用サーバー
  from-scratch/ ソケットから自作したHTTPサーバー（keep-alive対応）
  client/       ソケットから自作したHTTPクライアント

unix/   UNIXドメインソケット
  server/       Go版サーバー
  client/       Go版クライアント
  faker-app/    gofakeit で偽データを返す対話型アプリ（Go）
  python/       書籍のPythonコードと、faker 版の対話型アプリ

c10k/   C10K問題の比較ベンチ（詳細は下の「C10K ベンチ」）

rpc/    gRPC（Protocol Buffers）による RPC（詳細は下の「RPC」）

udp/    UDPソケット
  chat/         UDP のチャットメッセンジャー（詳細は下の「UDP チャット」）
  chatroom/     TCP でルームを作成・参加し、UDP で話すチャットルーム（詳細は下の「チャットルーム」）
```

## 動かし方

Go のサーバー:

```bash
go run ./unix/faker-app/server
```

Go のクライアント（別のターミナルで）:

```bash
go run ./unix/faker-app/client
```

Python の準備（初回だけ）:

```bash
python3 -m venv .venv
```

```bash
./.venv/bin/pip install faker
```

Python のサーバー:

```bash
./.venv/bin/python unix/python/faker-app/server.py
```

Python のクライアント（別のターミナルで）:

```bash
./.venv/bin/python unix/python/faker-app/client.py
```

Go版サーバーと Python版クライアントは同じプロトコル（1行=1メッセージ）なので相互に接続できる。

## C10K ベンチ

同じ行エコーサーバーを Python と Go で7種類（直列・1接続1スレッド・I/O多重化）書き、1万接続を張ったときの OS スレッド数・メモリ・応答成功率と、1件ごとに重い計算を入れたときの処理件数を比べる。

**計測結果と図は [c10k/README.md](c10k/README.md) にまとめている。**

1万接続の比較（全部で数分。`./c10k/bench.sh go-kqueue` のように名前を指定すると1つだけ）:

```bash
./c10k/bench.sh
```

1件ごとに重い計算を入れた比較（1分ほど。`WORK_MS=2` で計算量を変えられる）:

```bash
./c10k/cpu-bench.sh
```

## RPC

`rpc/proto/calc.proto` に関数（`Subtract` / `Floor` / `Nroot` / `Reverse` / `ValidAnagram` / `Sort`）と引数・戻り値の型を定義し、Python の gRPC サーバーを Node.js から呼ぶ。通信は UNIX ドメインソケット（`/tmp/calc.sock`）。

```
rpc/
  proto/calc.proto     サーバーとクライアントの約束（関数名と型）
  gen.sh               calc.proto から Python のコードを生成する
  python/server.py     gRPC サーバー
  python/wire_demo.py  同じリクエストを JSON と Protocol Buffers で表したバイト列を比べる
  node/client.js       gRPC クライアント（calc.proto を実行時に読み込む）
```

Python の gRPC を入れる（初回だけ）:

```bash
./.venv/bin/pip install grpcio grpcio-tools
```

Node.js の gRPC を入れる（初回だけ）:

```bash
npm --prefix rpc/node install
```

`calc.proto` から Python のコードを生成する（`.proto` を変えたらやり直す）:

```bash
./rpc/gen.sh
```

サーバーを起動する:

```bash
./.venv/bin/python rpc/python/server.py
```

クライアントを実行する（別のターミナルで）:

```bash
node rpc/node/client.js
```

## UDP チャット

サーバーが受け取ったメッセージを、参加中の他の全クライアントへ転送する UDP のチャット（Python、標準ライブラリのみ）。

**学習目的に対して何が学べたかと、その実装箇所は [udp/chat/README.md](udp/chat/README.md) にまとめている。**

```
udp/chat/
  protocol.py  パケット形式 [usernamelen 1バイト][username][message]（最大 4096 バイト、UTF-8）
  server.py    リレーサーバー（参加者を送信元アドレスで覚え、60 秒送信がないか 3 回連続で送信に失敗したら外す）
  client.py    CLI クライアント（ユーザー名を聞いてから 1 行 = 1 メッセージで送る）
  bench.py     1000 人に毎秒 10 通 = 毎秒 1 万パケットを転送できるかの負荷試験
```

UDP にはコネクションがないので、サーバーは「最近パケットを送ってきたアドレス」を参加者とみなす。クライアントは起動時に本文が空のパケットを参加の合図として送る。コードのコメントにある【機能要件N】【非機能要件N】は課題文の番号に対応している。

サーバーを起動する:

```bash
python3 udp/chat/server.py
```

クライアントを起動する（別のターミナルで。何人でも）:

```bash
python3 udp/chat/client.py
```

負荷試験は、サーバーをメッセージごとのログなし（`-q`）で起動してから:

```bash
python3 udp/chat/server.py -q
```

```bash
python3 udp/chat/bench.py
```

手元の Mac では 1000 人・毎秒 10 通で 5 万パケットすべてが届き、約 10,000 パケット/秒。`--rate 30` にしても全部届いた（約 30,000 パケット/秒）。

## チャットルーム

UDP チャットの続き（ステージ 2）。クライアントがチャットルームを作ってホストになり、他の人はルーム名（とパスワード）を指定して参加する。ルームの作成・参加は自作の TCP プロトコル（TCRP）でトークンを受け取り、会話はそのトークンを付けて UDP で行う。

**プロトコルの詳細、全体のシーケンス図、負荷試験の結果は [udp/chatroom/README.md](udp/chatroom/README.md) にまとめている。**

サーバーを起動する:

```bash
python3 udp/chatroom/server.py
```

クライアントを起動する（別のターミナルで。何人でも）:

```bash
python3 udp/chatroom/client.py
```
