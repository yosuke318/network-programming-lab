package main

import (
	"log"
	"net"
	"strings"
)

func main() {
	ln, err := net.Listen("tcp", "127.0.0.1:9000")
	if err != nil {
		log.Fatal(err)
	}
	defer ln.Close()
	log.Println("listening on 127.0.0.1:9000")

	for {
		conn, err := ln.Accept()
		if err != nil {
			log.Println("accept:", err)
			continue
		}
		go handle(conn)
	}
}

func handle(conn net.Conn) {
	defer conn.Close()
	log.Printf("connected: %s -> %s", conn.RemoteAddr(), conn.LocalAddr())

	buf := make([]byte, 1024)
	for {
		n, err := conn.Read(buf)
		if err != nil {
			log.Printf("disconnected: %s (%v)", conn.RemoteAddr(), err)
			return
		}
		got := buf[:n]
		log.Printf("recv %d bytes: %q  hex=% x", n, got, got)

		reply := strings.ToUpper(string(got))
		if _, err := conn.Write([]byte(reply)); err != nil {
			log.Println("write:", err)
			return
		}
	}
}
