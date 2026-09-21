package main

import (
	"bufio"
	"fmt"
	"log"
	"net"
	"os"
)

func main() {
	addr := "127.0.0.1:9000"
	if len(os.Args) > 1 {
		addr = os.Args[1]
	}
	conn, err := net.Dial("tcp", addr)
	if err != nil {
		log.Fatal(err)
	}
	defer conn.Close()
	fmt.Printf("connected %s -> %s\n", conn.LocalAddr(), conn.RemoteAddr())

	done := make(chan struct{})
	go func() {
		defer close(done)
		buf := make([]byte, 4096)
		for {
			n, err := conn.Read(buf)
			if n > 0 {
				fmt.Printf("< %q\n", buf[:n])
			}
			if err != nil {
				return
			}
		}
	}()

	stdin := bufio.NewScanner(os.Stdin)
	for stdin.Scan() {
		// Scannerは改行を削るが、HTTPなどは改行が構文なので付け直す。
		if _, err := fmt.Fprintf(conn, "%s\r\n", stdin.Text()); err != nil {
			log.Fatal(err)
		}
	}

	// ハーフクローズ。こちらの送信終了だけを伝え、相手の返信は読み続ける。
	conn.(*net.TCPConn).CloseWrite()
	<-done
}
