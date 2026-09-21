// ソケットだけでHTTPクライアントを組み立てる。net/http は使わない。
//
// サーバー側(from-scratch)と鏡写しで、やることは同じ2つ。
//   送信: リクエスト行 + ヘッダー + 空行 + ボディ を書く
//   受信: 空行までヘッダーを読み、Content-Length の数だけボディを読む
package main

import (
	"bufio"
	"flag"
	"fmt"
	"io"
	"log"
	"net"
	"strconv"
	"strings"
)

func main() {
	addr := flag.String("addr", "127.0.0.1:9003", "接続先 host:port")
	method := flag.String("method", "GET", "HTTPメソッド")
	path := flag.String("path", "/", "パス")
	body := flag.String("body", "", "リクエストボディ")
	flag.Parse()

	conn, err := net.Dial("tcp", *addr)
	if err != nil {
		log.Fatal(err)
	}
	defer conn.Close()

	req := buildRequest(*method, *path, *addr, []byte(*body))
	fmt.Printf("--- 送信した生バイト (%d bytes) ---\n%q\n\n", len(req), req)
	if _, err := conn.Write(req); err != nil {
		log.Fatal(err)
	}

	br := bufio.NewReader(conn)
	status, headers, respBody, err := readResponse(br)
	if err != nil {
		log.Fatal(err)
	}

	fmt.Printf("--- 受信 ---\nstatus: %s\n", status)
	for k, v := range headers {
		fmt.Printf("header: %s: %s\n", k, v)
	}
	fmt.Printf("body (%d bytes): %q\n", len(respBody), respBody)
}

func buildRequest(method, path, host string, body []byte) []byte {
	var sb strings.Builder
	fmt.Fprintf(&sb, "%s %s HTTP/1.1\r\n", method, path)
	// HTTP/1.1 では Host ヘッダーが必須。1つのIPで複数ドメインを捌くため。
	fmt.Fprintf(&sb, "Host: %s\r\n", host)
	fmt.Fprintf(&sb, "Content-Length: %d\r\n", len(body))
	// 1往復で終わらせたいので、サーバーに接続を閉じてよいと伝える。
	sb.WriteString("Connection: close\r\n")
	// ここの空行がヘッダーの終わり。これがないとサーバーは待ち続ける。
	sb.WriteString("\r\n")
	return append([]byte(sb.String()), body...)
}

func readResponse(br *bufio.Reader) (status string, headers map[string]string, body []byte, err error) {
	// 1行目: "HTTP/1.1 200 OK"
	status, err = readLine(br)
	if err != nil {
		return "", nil, nil, err
	}

	// 空行までがヘッダー。行数は決まっていない。
	headers = map[string]string{}
	for {
		line, err := readLine(br)
		if err != nil {
			return "", nil, nil, err
		}
		if line == "" {
			break
		}
		name, value, ok := strings.Cut(line, ":")
		if !ok {
			return "", nil, nil, fmt.Errorf("malformed header: %q", line)
		}
		headers[strings.ToLower(strings.TrimSpace(name))] = strings.TrimSpace(value)
	}

	// ボディの長さは Content-Length で決まる。
	// 無い場合は「接続が閉じるまでが本文」というルールにフォールバックする。
	if v, ok := headers["content-length"]; ok {
		n, err := strconv.Atoi(v)
		if err != nil || n < 0 {
			return "", nil, nil, fmt.Errorf("bad Content-Length: %q", v)
		}
		body = make([]byte, n)
		if _, err := io.ReadFull(br, body); err != nil {
			return "", nil, nil, fmt.Errorf("short body: %w", err)
		}
	} else {
		body, err = io.ReadAll(br)
		if err != nil {
			return "", nil, nil, err
		}
	}

	return status, headers, body, nil
}

func readLine(br *bufio.Reader) (string, error) {
	line, err := br.ReadString('\n')
	if err != nil {
		return "", err
	}
	return strings.TrimRight(line, "\r\n"), nil
}
