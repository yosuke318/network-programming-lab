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

c10k/   C10K問題の比較ベンチ（1万接続を7種類のサーバーで捌いて比べる）
  python/       直列・スレッド・selectors・asyncio の4種類
  go/goroutine/ goroutine 版（-lock-os-thread で1接続1OSスレッドを再現）
  go/kqueue/    kqueue を直接使ったI/O多重化版（macOS専用）
  go/loadgen/   負荷クライアント（接続数・OSスレッド数・メモリを計測）
  bench.sh      全サーバーを順に計測するスクリプト
  charts.py     計測結果のグラフを images/ に出力（matplotlib が必要）
  qiita.md      計測結果をまとめた記事
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

C10K ベンチ（全部で数分かかる。`./c10k/bench.sh go-kqueue` のように名前を指定すると1つだけ実行）:

```bash
./c10k/bench.sh
```
