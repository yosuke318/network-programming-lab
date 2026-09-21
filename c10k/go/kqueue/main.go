//go:build darwin

// kqueue を直接使った I/O多重化の行エコーサーバー（macOS / BSD 専用。Linux なら epoll を使う）。
//
// goroutine はメインの1本だけ。「読めるソケットはどれか」をOSに教えてもらい、
// 届いたものから順に処理する。Goのランタイムが goroutine の裏でやっていることを
// 手で書くとこうなる。
//
// net パッケージを使わず、socket() / bind() / listen() / accept() を直接呼んでいる。
package main

import (
	"bytes"
	"errors"
	"log"
	"os"
	"syscall"

	"netlab/c10k/go/cpuwork"
)

const port = 9202

// スレッドを使わないので、接続ごとの状態は自分で持つ必要がある。
// goroutine 版では bufio.Reader とスタック上の変数が暗黙に持っていたもの。
type conn struct {
	in       []byte // 改行が来るまで溜めておく受信データ
	out      []byte // 送りきれなかった応答
	watching bool   // 「書けるようになったら教えて」を登録中か
}

func main() {
	lfd, err := listen(port)
	if err != nil {
		log.Fatal(err)
	}
	kq, err := syscall.Kqueue()
	if err != nil {
		log.Fatal(err)
	}
	register(kq, lfd, syscall.EVFILT_READ, syscall.EV_ADD)
	log.Printf("kqueue server on 127.0.0.1:%d pid=%d", port, os.Getpid())

	conns := map[int]*conn{}
	events := make([]syscall.Kevent_t, 256)
	buf := make([]byte, 4096)

	for {
		// 何か起きるまでここで眠る。1万接続あっても、起こされるのは準備ができた分だけ。
		n, err := syscall.Kevent(kq, nil, events, nil)
		if err != nil {
			if errors.Is(err, syscall.EINTR) {
				continue
			}
			log.Fatal(err)
		}
		for _, ev := range events[:n] {
			fd := int(ev.Ident)
			switch {
			case fd == lfd:
				acceptAll(kq, lfd, conns)
			case ev.Filter == syscall.EVFILT_READ:
				onReadable(kq, fd, conns, buf)
			case ev.Filter == syscall.EVFILT_WRITE:
				if c := conns[fd]; c != nil {
					flush(kq, fd, c, conns)
				}
			}
		}
	}
}

func listen(port int) (int, error) {
	fd, err := syscall.Socket(syscall.AF_INET, syscall.SOCK_STREAM, 0)
	if err != nil {
		return -1, err
	}
	if err := syscall.SetsockoptInt(fd, syscall.SOL_SOCKET, syscall.SO_REUSEADDR, 1); err != nil {
		return -1, err
	}
	if err := syscall.Bind(fd, &syscall.SockaddrInet4{Port: port, Addr: [4]byte{127, 0, 0, 1}}); err != nil {
		return -1, err
	}
	if err := syscall.Listen(fd, 128); err != nil {
		return -1, err
	}
	// ノンブロッキングにしておかないと、accept や read で眠ってしまい他の接続を捌けない。
	if err := syscall.SetNonblock(fd, true); err != nil {
		return -1, err
	}
	return fd, nil
}

func acceptAll(kq, lfd int, conns map[int]*conn) {
	// 1回の通知で複数の接続が待っていることがあるので、空になるまで受け取る。
	for {
		nfd, _, err := syscall.Accept(lfd)
		if err != nil {
			if !errors.Is(err, syscall.EAGAIN) && !errors.Is(err, syscall.ECONNABORTED) {
				log.Println("accept:", err)
			}
			return
		}
		if err := syscall.SetNonblock(nfd, true); err != nil {
			syscall.Close(nfd)
			continue
		}
		register(kq, nfd, syscall.EVFILT_READ, syscall.EV_ADD)
		conns[nfd] = &conn{}
	}
}

func onReadable(kq, fd int, conns map[int]*conn, buf []byte) {
	c := conns[fd]
	if c == nil {
		return
	}
	n, err := syscall.Read(fd, buf)
	if err != nil {
		if errors.Is(err, syscall.EAGAIN) {
			return
		}
		closeConn(fd, conns)
		return
	}
	if n == 0 { // 相手が閉じた（EOF）
		closeConn(fd, conns)
		return
	}

	// 届いた分を溜め、改行が揃った行だけ応答に回す。境界問題はここでも自分で解く。
	c.in = append(c.in, buf[:n]...)
	for {
		i := bytes.IndexByte(c.in, '\n')
		if i < 0 {
			break
		}
		// ここで計算している間、他の1万接続は誰も処理されない。
		cpuwork.Burn()
		c.out = append(c.out, c.in[:i+1]...)
		c.in = c.in[i+1:]
	}
	flush(kq, fd, c, conns)
}

func flush(kq, fd int, c *conn, conns map[int]*conn) {
	for len(c.out) > 0 {
		n, err := syscall.Write(fd, c.out)
		if err != nil {
			if errors.Is(err, syscall.EAGAIN) {
				break // 送信バッファが一杯。書けるようになったら続きを送る
			}
			closeConn(fd, conns)
			return
		}
		c.out = c.out[n:]
	}

	switch {
	case len(c.out) > 0 && !c.watching:
		register(kq, fd, syscall.EVFILT_WRITE, syscall.EV_ADD)
		c.watching = true
	case len(c.out) == 0 && c.watching:
		register(kq, fd, syscall.EVFILT_WRITE, syscall.EV_DELETE)
		c.watching = false
	}
}

func closeConn(fd int, conns map[int]*conn) {
	// close すると kqueue への登録も自動で消える。
	syscall.Close(fd)
	delete(conns, fd)
}

func register(kq, fd, filter, flags int) {
	var ev syscall.Kevent_t
	syscall.SetKevent(&ev, fd, filter, flags)
	if _, err := syscall.Kevent(kq, []syscall.Kevent_t{ev}, nil, nil); err != nil {
		log.Printf("kevent fd=%d: %v", fd, err)
	}
}
