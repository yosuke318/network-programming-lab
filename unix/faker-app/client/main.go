// ユーザーの入力を1行ずつサーバーへ送り、応答を表示するクライアント。
// Python版(unix/python/faker-app)と同じプロトコルなので、相互に接続できる。
package main

import (
	"bufio"
	"fmt"
	"io"
	"log"
	"net"
	"os"
	"strings"
)

const socketPath = "/tmp/faker_socket"

func main() {
	fmt.Printf("connecting to %s\n", socketPath)

	conn, err := net.Dial("unix", socketPath)
	if err != nil {
		fmt.Println(err)
		os.Exit(1)
	}
	defer func() {
		fmt.Println("closing socket")
		conn.Close()
	}()

	fmt.Println("コマンドを入力してください（help で一覧、quit で終了）")

	stdin := bufio.NewScanner(os.Stdin)
	server := bufio.NewReader(conn)

	for {
		fmt.Print("> ")
		if !stdin.Scan() {
			fmt.Println()
			return
		}
		message := strings.TrimSpace(stdin.Text())
		if message == "" {
			continue
		}

		if _, err := fmt.Fprintf(conn, "%s\n", message); err != nil {
			log.Fatal(err)
		}

		response, err := server.ReadString('\n')
		if err != nil {
			// EOF = 相手が接続を閉じた。
			if err == io.EOF {
				fmt.Println("サーバーが接続を閉じました")
				return
			}
			log.Fatal(err)
		}
		fmt.Printf("< %s\n", strings.TrimRight(response, "\n"))

		if strings.EqualFold(message, "quit") {
			return
		}
	}
}
