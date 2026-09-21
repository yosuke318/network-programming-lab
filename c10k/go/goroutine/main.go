// 従来のGoの書き方。1接続に1 goroutine を割り当てる行エコーサーバー。
//
// -lock-os-thread を付けると、各 goroutine を専用のOSスレッドに固定する。
// 違いは runtime.LockOSThread() の1行だけ。これで「1接続1スレッド」方式を再現できる。
package main

import (
	"bufio"
	"flag"
	"log"
	"net"
	"os"
	"runtime"

	"netlab/c10k/go/cpuwork"
)

func main() {
	addr := flag.String("addr", "127.0.0.1:9200", "待ち受けアドレス")
	lock := flag.Bool("lock-os-thread", false, "goroutine をOSスレッドに固定する（1接続1スレッドの再現）")
	flag.Parse()

	ln, err := net.Listen("tcp", *addr)
	if err != nil {
		log.Fatal(err)
	}
	log.Printf("goroutine server on %s lock-os-thread=%v pid=%d", *addr, *lock, os.Getpid())

	for {
		conn, err := ln.Accept()
		if err != nil {
			log.Println("accept:", err)
			continue
		}
		go func() {
			if *lock {
				// この goroutine が終わるまで、OSスレッドを1本占有する。
				runtime.LockOSThread()
			}
			handle(conn)
		}()
	}
}

func handle(conn net.Conn) {
	defer conn.Close()
	br := bufio.NewReader(conn)
	for {
		// データが来るまでここで止まるが、止まるのは goroutine だけ。
		// OSスレッドはランタイムが別の goroutine の実行に回す。
		line, err := br.ReadBytes('\n')
		if err != nil {
			return
		}
		cpuwork.Burn()
		if _, err := conn.Write(line); err != nil {
			return
		}
	}
}
