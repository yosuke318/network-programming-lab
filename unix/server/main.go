package main

import (
	"errors"
	"fmt"
	"io"
	"log"
	"net"
	"os"
)

const socketPath = "/tmp/socket_file"

func main() {
	// UNIXドメインソケットはファイルを残すので、bindする前に残骸を消す。
	if err := os.Remove(socketPath); err != nil && !errors.Is(err, os.ErrNotExist) {
		log.Fatal(err)
	}

	fmt.Printf("Starting up on %s\n", socketPath)

	// net.Listen が socket() + bind() + listen() をまとめて行う。
	ln, err := net.Listen("unix", socketPath)
	if err != nil {
		log.Fatal(err)
	}
	defer ln.Close()

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
	defer func() {
		fmt.Println("Closing current connection")
		conn.Close()
	}()
	fmt.Printf("connection from %q\n", conn.RemoteAddr())

	buf := make([]byte, 16)
	for {
		n, err := conn.Read(buf)
		if n > 0 {
			chunk := string(buf[:n])
			fmt.Printf("Received %s\n", chunk)
			if _, err := conn.Write([]byte("Processing " + chunk)); err != nil {
				log.Println("write:", err)
				return
			}
		}
		if err != nil {
			if errors.Is(err, io.EOF) {
				fmt.Printf("no data from %q\n", conn.RemoteAddr())
			} else {
				log.Println("read:", err)
			}
			return
		}
	}
}
