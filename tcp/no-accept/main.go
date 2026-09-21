package main

import (
	"log"
	"net"
	"time"
)

// listen するが Accept を一度も呼ばないサーバー。
// それでもカーネルが3-wayハンドシェイクを完了してキューに積むため、
// クライアント側の connect() は成功する。
// つまり accept() は接続を「作る」のではなく「受け取る」だけだと分かる。
func main() {
	ln, err := net.Listen("tcp", "127.0.0.1:9002")
	if err != nil {
		log.Fatal(err)
	}
	defer ln.Close()
	log.Println("listening on 127.0.0.1:9002 — will NEVER call Accept()")
	time.Sleep(5 * time.Minute)
}
