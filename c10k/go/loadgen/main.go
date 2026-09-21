// C10K の負荷をかけるクライアント。
//
//  1. n 本の接続を張る
//  2. 何も送らずに放置し、その間のサーバーのスレッド数とメモリを測る
//     （C10K の接続の大半は「待っているだけ」なので、それを再現する）
//  3. 全接続から同時に1行送り、応答が返ってくるか確かめる
package main

import (
	"bufio"
	"errors"
	"flag"
	"fmt"
	"io"
	"net"
	"os/exec"
	"sort"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"
)

func main() {
	addr := flag.String("addr", "127.0.0.1:9200", "接続先")
	n := flag.Int("n", 10000, "接続数")
	pid := flag.Int("pid", 0, "計測するサーバーのPID（0なら計測しない）")
	// accept キューの上限（macOS の somaxconn は128）を超えて一斉に接続すると、
	// 溢れた分をカーネルが捨ててしまい、サーバー方式の比較にならない。なので128未満に抑える。
	dialConcurrency := flag.Int("dial-concurrency", 50, "同時に接続を試みる数")
	timeout := flag.Duration("timeout", 3*time.Second, "接続・応答のタイムアウト")
	hold := flag.Duration("hold", 2*time.Second, "放置する時間")
	flag.Parse()

	fmt.Printf("target=%s n=%d\n", *addr, *n)
	if *pid > 0 {
		fmt.Printf("server before : %s\n", sample(*pid))
	}

	// 1. 接続を張る
	conns := make([]net.Conn, *n)
	dialErrs := newCounter()
	sem := make(chan struct{}, *dialConcurrency)
	var wg sync.WaitGroup
	start := time.Now()
	for i := range *n {
		wg.Add(1)
		sem <- struct{}{}
		go func() {
			defer wg.Done()
			defer func() { <-sem }()
			c, err := net.DialTimeout("tcp", *addr, *timeout)
			if err != nil {
				dialErrs.add(classify(err))
				return
			}
			conns[i] = c
		}()
	}
	wg.Wait()
	connected := 0
	for _, c := range conns {
		if c != nil {
			connected++
		}
	}
	fmt.Printf("connect       : %d ok / %d failed (%.2fs)%s\n",
		connected, *n-connected, time.Since(start).Seconds(), dialErrs)

	// 2. 放置して計測
	time.Sleep(*hold)
	if *pid > 0 {
		fmt.Printf("server holding: %s\n", sample(*pid))
	}

	// 3. 全接続から同時に1行送る
	var mu sync.Mutex
	var latencies []time.Duration
	pingErrs := newCounter()
	start = time.Now()
	for _, c := range conns {
		if c == nil {
			continue
		}
		wg.Add(1)
		go func() {
			defer wg.Done()
			t0 := time.Now()
			c.SetDeadline(t0.Add(*timeout))
			if _, err := io.WriteString(c, "ping\n"); err != nil {
				pingErrs.add(classify(err))
				return
			}
			line, err := bufio.NewReader(c).ReadString('\n')
			if err != nil {
				pingErrs.add(classify(err))
				return
			}
			if line != "ping\n" {
				pingErrs.add("bad reply")
				return
			}
			mu.Lock()
			latencies = append(latencies, time.Since(t0))
			mu.Unlock()
		}()
	}
	wg.Wait()
	fmt.Printf("ping          : %d ok / %d failed (%.2fs) p50=%v p99=%v%s\n",
		len(latencies), connected-len(latencies), time.Since(start).Seconds(),
		percentile(latencies, 50), percentile(latencies, 99), pingErrs)
	if *pid > 0 {
		fmt.Printf("server after  : %s\n", sample(*pid))
	}

	for _, c := range conns {
		if c != nil {
			c.Close()
		}
	}
}

// ps でサーバーのOSスレッド数と常駐メモリ(RSS)を取る。macOS の ps 前提。
func sample(pid int) string {
	p := strconv.Itoa(pid)
	rss, err := exec.Command("ps", "-o", "rss=", "-p", p).Output()
	if err != nil {
		return "プロセスが存在しない（落ちた）"
	}
	// ps -M はヘッダー1行 + スレッドごとに1行を出す。
	out, _ := exec.Command("ps", "-M", "-p", p).Output()
	threads := strings.Count(strings.TrimSpace(string(out)), "\n")
	kb, _ := strconv.Atoi(strings.TrimSpace(string(rss)))
	return fmt.Sprintf("threads=%d rss=%.1fMB", threads, float64(kb)/1024)
}

func classify(err error) string {
	var ne net.Error
	switch {
	case errors.As(err, &ne) && ne.Timeout():
		return "timeout"
	case errors.Is(err, io.EOF):
		return "EOF"
	case errors.Is(err, syscall.ECONNRESET):
		return "connection reset"
	case errors.Is(err, syscall.ECONNREFUSED):
		return "connection refused"
	case errors.Is(err, syscall.EPIPE):
		return "broken pipe"
	case errors.Is(err, syscall.EADDRNOTAVAIL):
		return "no ephemeral port"
	}
	return err.Error()
}

func percentile(ds []time.Duration, p int) time.Duration {
	if len(ds) == 0 {
		return 0
	}
	s := append([]time.Duration(nil), ds...)
	sort.Slice(s, func(i, j int) bool { return s[i] < s[j] })
	return s[(len(s)-1)*p/100].Round(time.Microsecond)
}

type counter struct {
	mu sync.Mutex
	m  map[string]int
}

func newCounter() *counter { return &counter{m: map[string]int{}} }

func (c *counter) add(k string) {
	c.mu.Lock()
	c.m[k]++
	c.mu.Unlock()
}

func (c *counter) String() string {
	c.mu.Lock()
	defer c.mu.Unlock()
	if len(c.m) == 0 {
		return ""
	}
	keys := make([]string, 0, len(c.m))
	for k := range c.m {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	parts := make([]string, len(keys))
	for i, k := range keys {
		parts[i] = fmt.Sprintf("%s×%d", k, c.m[k])
	}
	return " [" + strings.Join(parts, ", ") + "]"
}
