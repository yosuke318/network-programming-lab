package main

import (
	"errors"
	"fmt"
	"log"
	"net"
	"os"
	"time"
)

const socketPath = "/tmp/socket_file"

func main() {
	fmt.Printf("connecting to %s\n", socketPath)

	// net.Dial が socket() + connect() をまとめて行う。
	conn, err := net.Dial("unix", socketPath)
	if err != nil {
		fmt.Println(err)
		os.Exit(1)
	}
	defer func() {
		fmt.Println("closing socket")
		conn.Close()
	}()

	message := []byte("Sending a message to the server side")
	fmt.Printf("sending %d bytes\n", len(message))
	if _, err := conn.Write(message); err != nil {
		log.Fatal(err)
	}

	conn.SetReadDeadline(time.Now().Add(2 * time.Second))

	buf := make([]byte, 32)
	for {
		n, err := conn.Read(buf)
		if n > 0 {
			fmt.Printf("Server response: %q\n", buf[:n])
		}
		if err != nil {
			var netErr net.Error
			if errors.As(err, &netErr) && netErr.Timeout() {
				fmt.Println("Socket timeout, ending listening for server messages")
			}
			return
		}
	}
}
