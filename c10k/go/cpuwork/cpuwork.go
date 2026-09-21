// Package cpuwork は、1リクエストごとに一定量のCPU計算をさせるためのもの。
//
// 量は環境変数 WORK_MS（ミリ秒）で決める。未指定か0なら何もしない。
// 起動時に「このマシンで何回ループを回せば WORK_MS になるか」を測って決める。
package cpuwork

import (
	"log"
	"os"
	"strconv"
	"sync/atomic"
	"time"
)

var (
	iters int
	// 計算結果をどこにも使わないと、コンパイラにループごと消されてしまうので捨て場に足す。
	sink atomic.Uint64
)

func init() {
	ms, _ := strconv.ParseFloat(os.Getenv("WORK_MS"), 64)
	if ms <= 0 {
		return
	}
	iters = calibrate(ms)
	log.Printf("cpuwork: WORK_MS=%v iters=%d", ms, iters)
}

func spin(n int) uint64 {
	var x uint64
	for i := 0; i < n; i++ {
		x = x*31 + uint64(i)
	}
	return x
}

func calibrate(ms float64) int {
	n := 1 << 16
	for {
		start := time.Now()
		sink.Add(spin(n))
		elapsed := time.Since(start)
		if elapsed >= 50*time.Millisecond {
			perMs := float64(n) / (float64(elapsed) / float64(time.Millisecond))
			return int(perMs * ms)
		}
		n *= 2
	}
}

// Burn は WORK_MS ぶんのCPU計算をする。
func Burn() {
	if iters > 0 {
		sink.Add(spin(iters))
	}
}
