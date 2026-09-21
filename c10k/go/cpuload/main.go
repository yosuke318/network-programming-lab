// 1リクエストごとに重い計算をするサーバーに対して、処理能力を測るクライアント。
//
// c 本の接続それぞれが「1行送る → 応答を待つ → 次を送る」を duration の間くり返し、
// 何件捌けたか、1件の応答にかかった時間、サーバーが使ったCPUコア数を出す。
// コア数は「サーバーが使ったCPU時間 ÷ 経過時間」で求める（1.0 なら1コアをずっと使い切った）。
package main

import (
	"bufio"
	"flag"
	"fmt"
	"io"
	"log"
	"net"
	"os/exec"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"
)

func main() {
	addr := flag.String("addr", "127.0.0.1:9200", "接続先")
	c := flag.Int("c", 64, "同時に使う接続数")
	duration := flag.Duration("duration", 5*time.Second, "計測時間")
	pid := flag.Int("pid", 0, "計測するサーバーのPID")
	flag.Parse()

	conns := make([]net.Conn, *c)
	for i := range conns {
		conn, err := net.DialTimeout("tcp", *addr, 3*time.Second)
		if err != nil {
			log.Fatal(err)
		}
		conns[i] = conn
	}

	cpu0 := cpuSeconds(*pid)
	start := time.Now()
	deadline := start.Add(*duration)

	var mu sync.Mutex
	var latencies []time.Duration
	errs := 0
	var wg sync.WaitGroup
	for _, conn := range conns {
		wg.Add(1)
		go func() {
			defer wg.Done()
			br := bufio.NewReader(conn)
			var mine []time.Duration
			for time.Now().Before(deadline) {
				t0 := time.Now()
				conn.SetDeadline(t0.Add(30 * time.Second))
				if _, err := io.WriteString(conn, "ping\n"); err != nil {
					mu.Lock()
					errs++
					mu.Unlock()
					return
				}
				if _, err := br.ReadString('\n'); err != nil {
					mu.Lock()
					errs++
					mu.Unlock()
					return
				}
				mine = append(mine, time.Since(t0))
			}
			mu.Lock()
			latencies = append(latencies, mine...)
			mu.Unlock()
		}()
	}
	wg.Wait()
	wall := time.Since(start).Seconds()
	cpu1 := cpuSeconds(*pid)

	sort.Slice(latencies, func(i, j int) bool { return latencies[i] < latencies[j] })
	fmt.Printf("requests      : %d in %.2fs = %.0f req/s (errors=%d)\n",
		len(latencies), wall, float64(len(latencies))/wall, errs)
	fmt.Printf("latency       : p50=%v p99=%v\n", pct(latencies, 50), pct(latencies, 99))
	if *pid > 0 {
		fmt.Printf("server cpu    : %.2f cores\n", (cpu1-cpu0)/wall)
	}

	for _, conn := range conns {
		conn.Close()
	}
}

// ps -o time= はプロセスが使ったCPU時間の累計（例: 1:02.34 = 1分2.34秒）を返す。
func cpuSeconds(pid int) float64 {
	if pid == 0 {
		return 0
	}
	out, err := exec.Command("ps", "-o", "time=", "-p", strconv.Itoa(pid)).Output()
	if err != nil {
		return 0
	}
	total := 0.0
	for _, part := range strings.Split(strings.TrimSpace(string(out)), ":") {
		v, _ := strconv.ParseFloat(part, 64)
		total = total*60 + v
	}
	return total
}

func pct(ds []time.Duration, p int) time.Duration {
	if len(ds) == 0 {
		return 0
	}
	return ds[(len(ds)-1)*p/100].Round(10 * time.Microsecond)
}
