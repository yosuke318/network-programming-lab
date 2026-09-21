"""1リクエストごとに一定量のCPU計算をさせるためのもの。

量は環境変数 WORK_MS（ミリ秒）で決める。未指定か0なら何もしない。
起動時に「このマシンで何回ループを回せば WORK_MS になるか」を測って決める。
純粋な Python のループなので、計算している間は GIL を握り続ける。
"""

import os
import time

WORK_MS = float(os.environ.get('WORK_MS', '0'))


def _spin(n):
    x = 0
    for i in range(n):
        x = (x * 31 + i) & 0xFFFFFFFF
    return x


def _calibrate(ms):
    n = 1 << 10
    while True:
        start = time.perf_counter()
        _spin(n)
        elapsed = time.perf_counter() - start
        if elapsed >= 0.05:
            return max(1, int(n * ms / (elapsed * 1000)))
        n *= 2


ITERS = _calibrate(WORK_MS) if WORK_MS > 0 else 0
if ITERS:
    print('work: WORK_MS={} iters={}'.format(WORK_MS, ITERS), flush=True)


def burn():
    """WORK_MS ぶんのCPU計算をする。"""
    if ITERS:
        _spin(ITERS)
