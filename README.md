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
```

## 動かし方

Go:

```bash
go run ./unix/faker-app/server
go run ./unix/faker-app/client
```

Python（`faker` が必要）:

```bash
python3 -m venv .venv && ./.venv/bin/pip install faker
./.venv/bin/python unix/python/faker-app/server.py
./.venv/bin/python unix/python/faker-app/client.py
```

Go版サーバーと Python版クライアントは同じプロトコル（1行=1メッセージ）なので相互に接続できる。

## C10K ベンチ

同じ行エコーサーバーを Python と Go で7種類（直列・1接続1スレッド・I/O多重化）書き、1万接続を張ったときの OS スレッド数・メモリ・応答成功率と、1件ごとに重い計算を入れたときの処理件数を比べる。

**計測結果と図は [c10k/README.md](c10k/README.md) にまとめている。**

```bash
./c10k/bench.sh       # 1万接続（全部で数分。./c10k/bench.sh go-kqueue のように名前を指定すると1つだけ）
./c10k/cpu-bench.sh   # 1件ごとに重い計算を入れた比較（1分ほど。WORK_MS=2 で計算量を変えられる）
```
