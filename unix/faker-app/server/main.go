// クライアントからのコマンドを受け取り、gofakeit で作った偽データを返すサーバー。
// Python版(unix/python/faker-app)と同じプロトコルを喋るので、相互に接続できる。
//
// プロトコル: 1行 = 1メッセージ（改行区切り、UTF-8）。
package main

import (
	"bufio"
	"errors"
	"fmt"
	"log"
	"net"
	"os"
	"os/signal"
	"sort"
	"strings"
	"syscall"

	"github.com/brianvoe/gofakeit/v7"
)

const socketPath = "/tmp/faker_socket"

// 関数を値として map に入れられるのがGoの特徴。Python版の COMMANDS と同じ構造。
var commands = map[string]func() string{
	"name":    gofakeit.Name,
	"email":   gofakeit.Email,
	"company": gofakeit.Company,
	"address": func() string { return gofakeit.Address().Address },
	"text":    func() string { return gofakeit.Paragraph(2, 3, 8, " ") },
	"profile": func() string {
		return fmt.Sprintf("%s / %s / %s", gofakeit.Name(), gofakeit.Email(), gofakeit.Company())
	},
}

func main() {
	// 前回が異常終了していた場合に備えて残骸を消す。
	if err := os.Remove(socketPath); err != nil && !errors.Is(err, os.ErrNotExist) {
		log.Fatal(err)
	}

	ln, err := net.Listen("unix", socketPath)
	if err != nil {
		log.Fatal(err)
	}
	log.Printf("Starting up on %s", socketPath)

	// Ctrl-C で Listener を閉じる。Goの unix Listener は Close 時に
	// ソケットファイルを自動で消してくれるので、後片付けが要らない。
	sigCh := make(chan os.Signal, 1)
	signal.Notify(sigCh, os.Interrupt, syscall.SIGTERM)
	go func() {
		<-sigCh
		log.Println("shutting down")
		ln.Close()
	}()

	for {
		conn, err := ln.Accept()
		if err != nil {
			// Listener が閉じられたら終了。
			if errors.Is(err, net.ErrClosed) {
				return
			}
			log.Println("accept:", err)
			continue
		}
		// Python版は1接続ずつしか捌けないが、Goはこの1行で同時に捌ける。
		go serve(conn)
	}
}

func serve(conn net.Conn) {
	defer func() {
		log.Println("--- connection closed ---")
		conn.Close()
	}()
	log.Println("--- connection opened ---")

	// bufio.Scanner が「改行まで」を溜めてくれる。Python の makefile と同じ役割。
	scanner := bufio.NewScanner(conn)
	writer := bufio.NewWriter(conn)

	for scanner.Scan() {
		message := scanner.Text()
		log.Printf("Received: %q", message)

		if strings.EqualFold(strings.TrimSpace(message), "quit") {
			writeLine(writer, "さようなら")
			return
		}

		response := sanitize(makeResponse(message))
		log.Printf("Sending : %q", response)
		if err := writeLine(writer, response); err != nil {
			log.Println("write:", err)
			return
		}
	}
	if err := scanner.Err(); err != nil {
		log.Println("read:", err)
	}
}

func makeResponse(message string) string {
	key := strings.ToLower(strings.TrimSpace(message))
	if key == "help" {
		names := make([]string, 0, len(commands))
		for name := range commands {
			names = append(names, name)
		}
		// map の走査順はGoでは毎回ランダムなので、並べたいなら明示的にソートする。
		sort.Strings(names)
		return "コマンド一覧: " + strings.Join(names, ", ") + ", help, quit"
	}
	if fn, ok := commands[key]; ok {
		return fn()
	}
	return fmt.Sprintf("未知のコマンド %q。help で一覧を表示します。", strings.TrimSpace(message))
}

// 改行区切りプロトコルなので、本文に改行を含められない。
func sanitize(text string) string {
	return strings.NewReplacer("\r\n", " / ", "\n", " / ").Replace(text)
}

// bufio.Writer は書いただけでは送られない。Flush が Python の flush() にあたる。
func writeLine(w *bufio.Writer, line string) error {
	if _, err := w.WriteString(line + "\n"); err != nil {
		return err
	}
	return w.Flush()
}
