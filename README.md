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
