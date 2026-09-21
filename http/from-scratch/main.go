// ソケットだけでHTTPサーバーを組み立てる。net/http は使わない。
//
// TCPはバイトの流れでしかなく「1メッセージ」の区切りを持たないので、
// 区切りは HTTP 側の約束事で決める。ここでやっているのは2つだけ。
//   1. 空行 (\r\n\r\n) が来るまで = ヘッダー
//   2. Content-Length の数だけ読む = ボディ
package main

import (
	"bufio"
	"errors"
	"fmt"
	"io"
	"log"
	"net"
	"strconv"
	"strings"
)

type request struct {
	method  string
	path    string
	proto   string
	headers map[string]string
	body    []byte
}

func main() {
	ln, err := net.Listen("tcp", "127.0.0.1:9003")
	if err != nil {
		log.Fatal(err)
	}
	defer ln.Close()
	log.Println("listening on 127.0.0.1:9003")

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
	log.Printf("open: %s", conn.RemoteAddr())

	// bufio.Reader がバラバラに届くバイト列を溜めてくれるので、
	// 「1行読む」「N バイト読む」という単位で考えられるようになる。
	br := bufio.NewReader(conn)

	// keep-alive。1本の接続で複数リクエストを捌く。
	// これが成立するのは、どこで1つ目が終わるかを Content-Length で言い切れるから。
	for {
		req, err := readRequest(br)
		if err != nil {
			if !errors.Is(err, io.EOF) {
				log.Printf("bad request from %s: %v", conn.RemoteAddr(), err)
				writeResponse(conn, 400, "Bad Request", []byte(err.Error()+"\n"), true)
			}
			log.Printf("close: %s", conn.RemoteAddr())
			return
		}

		log.Printf("%s %s %s (body %d bytes)", req.method, req.path, req.proto, len(req.body))

		closing := strings.EqualFold(req.headers["connection"], "close")
		body := fmt.Sprintf("method=%s path=%s body=%q\n", req.method, req.path, req.body)
		if err := writeResponse(conn, 200, "OK", []byte(body), closing); err != nil {
			log.Printf("write: %v", err)
			return
		}
		if closing {
			log.Printf("close: %s", conn.RemoteAddr())
			return
		}
	}
}

func readRequest(br *bufio.Reader) (*request, error) {
	// 1行目: "GET /path HTTP/1.1"
	line, err := readLine(br)
	if err != nil {
		return nil, err
	}
	parts := strings.Fields(line)
	if len(parts) != 3 {
		return nil, fmt.Errorf("malformed request line: %q", line)
	}
	req := &request{
		method:  parts[0],
		path:    parts[1],
		proto:   parts[2],
		headers: map[string]string{},
	}

	// 2行目以降: 空行が来るまでがヘッダー。ここが最初の「区切り」。
	for {
		line, err := readLine(br)
		if err != nil {
			return nil, err
		}
		if line == "" {
			break
		}
		name, value, ok := strings.Cut(line, ":")
		if !ok {
			return nil, fmt.Errorf("malformed header: %q", line)
		}
		// ヘッダー名は大文字小文字を区別しないので小文字に寄せる。
		req.headers[strings.ToLower(strings.TrimSpace(name))] = strings.TrimSpace(value)
	}

	// ボディ: Content-Length の数だけ読む。これが2つ目の「区切り」。
	if v, ok := req.headers["content-length"]; ok {
		n, err := strconv.Atoi(v)
		if err != nil || n < 0 {
			return nil, fmt.Errorf("bad Content-Length: %q", v)
		}
		req.body = make([]byte, n)
		// ReadFull は n バイト揃うまで何度でも読む。
		// 1回の Read では足りないことがある、が今日の学びそのもの。
		if _, err := io.ReadFull(br, req.body); err != nil {
			return nil, fmt.Errorf("short body: %w", err)
		}
	}

	return req, nil
}

func readLine(br *bufio.Reader) (string, error) {
	line, err := br.ReadString('\n')
	if err != nil {
		return "", err
	}
	return strings.TrimRight(line, "\r\n"), nil
}

func writeResponse(conn net.Conn, code int, reason string, body []byte, closing bool) error {
	var sb strings.Builder
	fmt.Fprintf(&sb, "HTTP/1.1 %d %s\r\n", code, reason)
	fmt.Fprintf(&sb, "Content-Type: text/plain; charset=utf-8\r\n")
	// これを書かないと、相手はボディがどこで終わるか判断できない。
	fmt.Fprintf(&sb, "Content-Length: %d\r\n", len(body))
	if closing {
		fmt.Fprintf(&sb, "Connection: close\r\n")
	}
	sb.WriteString("\r\n")

	if _, err := io.WriteString(conn, sb.String()); err != nil {
		return err
	}
	_, err := conn.Write(body)
	return err
}
