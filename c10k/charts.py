"""C10K ベンチの計測結果をグラフにする。

数値は 2026-09-21 に Apple M1 / 16GB / macOS 14.7.8 で計測したもの。
./c10k/bench.sh は1回、./c10k/cpu-bench.sh は3回実行した結果。
実行: ./.venv/bin/python c10k/charts.py   （matplotlib が必要）
出力: c10k/images/*.png
"""

from pathlib import Path

import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

OUT = Path(__file__).parent / 'images'

SURFACE = '#fcfcfb'
INK = '#0b0b0b'
INK_2 = '#52514e'
MUTED = '#898781'
GRID = '#e1e0d9'
BASELINE = '#c3c2b7'

# 色は「方式」を表す。検証済みの分類パレットの先頭3色を固定の順で使う。
MODELS = {
    'seq': ('① 直列', '#2a78d6'),
    'thread': ('② 1接続1OSスレッド', '#eb6834'),
    'mux': ('③ I/O多重化', '#1baf7a'),
}

# (表示名, 方式)
ROWS = [
    ('Python 直列', 'seq'),
    ('Python スレッド', 'thread'),
    ('Go OSスレッド固定', 'thread'),
    ('Python selectors', 'mux'),
    ('Python asyncio', 'mux'),
    ('Go goroutine', 'mux'),
    ('Go kqueue', 'mux'),
]

plt.rcParams.update({
    'font.family': 'Hiragino Sans',
    'font.size': 10,
    'axes.unicode_minus': False,
})


def base_axes(title, subtitle, xlabel):
    fig, ax = plt.subplots(figsize=(8, 4.4), dpi=200)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    for side in ('top', 'right', 'left'):
        ax.spines[side].set_visible(False)
    ax.spines['bottom'].set_color(BASELINE)
    ax.tick_params(axis='x', colors=MUTED, length=0)
    ax.tick_params(axis='y', colors=INK_2, length=0, labelsize=10)
    ax.grid(axis='x', color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.set_xlabel(xlabel, color=MUTED, fontsize=9)
    fig.text(0.02, 0.965, title, fontsize=13, color=INK, weight='bold', va='top')
    fig.text(0.02, 0.905, subtitle, fontsize=9, color=INK_2, va='top')
    return fig, ax


def model_bars(ax, values, labels, top_pad=0.5, rows=ROWS):
    """values: None なら棒を描かずラベルだけ出す（計測できなかった行）。"""
    ys = range(len(rows))
    for y, (name, model), v, label in zip(ys, rows, values, labels):
        if v is not None:
            ax.barh(y, v, height=0.62, color=MODELS[model][1], zorder=2)
        # 値は系列色ではなく文字色で書く。色は棒が持つ。
        x = v if v is not None else 0
        ax.annotate(label, (x, y), xytext=(6, 0), textcoords='offset points',
                    va='center', fontsize=9, color=INK if v is not None else INK_2)
    ax.set_yticks(list(ys), [r[0] for r in rows])
    # 棒の無い行があっても全行が同じ間隔で並ぶよう、範囲を明示する（上下反転して先頭を上に）。
    ax.set_ylim(len(rows) - 0.5, -top_pad)


def legend(fig, models=tuple(MODELS)):
    handles = [Patch(color=MODELS[m][1], label=MODELS[m][0]) for m in models]
    fig.legend(handles=handles, loc='upper right', bbox_to_anchor=(0.98, 0.975),
               ncol=3, frameon=False, fontsize=9, labelcolor=INK_2,
               handlelength=1.0, handleheight=0.9, columnspacing=1.2)


def finish(fig, name):
    fig.subplots_adjust(left=0.2, right=0.96, top=0.8, bottom=0.13)
    OUT.mkdir(exist_ok=True)
    fig.savefig(OUT / name, facecolor=SURFACE)
    plt.close(fig)
    print('wrote', OUT / name)


def success_chart():
    fig, ax = base_axes('全接続から1行送って、応答が返った割合',
                        '1万接続を張って放置したあと一斉に送信（直列のみ300接続）・1回の計測',
                        '応答成功率（%）')
    values = [1 / 300 * 100, 643 / 100, 0, 100, 9102 / 100, 9985 / 100, 100]
    labels = ['0.3%（300本中1本）', '6.4%', '0%（プロセスが落ちた）',
              '100%', '91.0%', '99.9%', '100%']
    model_bars(ax, values, labels)
    ax.set_xlim(0, 125)
    ax.set_xticks([0, 25, 50, 75, 100])
    legend(fig)
    finish(fig, 'c10k-success.png')


def threads_chart():
    fig, ax = base_axes('1万接続を抱えている間のOSスレッド数',
                        'ps -M で計測・1回の計測',
                        'OSスレッド数')
    values = [1, 4096, None, 1, 1, 10, 5]
    labels = ['1', '4096（上限で頭打ち）', '計測前にプロセスが落ちた',
              '1', '1', '10', '5']
    model_bars(ax, values, labels, top_pad=1.2)
    ax.axvline(4096, color=INK_2, linestyle=(0, (4, 3)), linewidth=1, zorder=3)
    ax.annotate('macOS の1プロセス上限 4096本', (4096, -0.85), xytext=(-6, 0),
                textcoords='offset points', ha='right', va='center',
                fontsize=8.5, color=INK_2)
    ax.set_xlim(0, 5600)
    legend(fig)
    finish(fig, 'c10k-threads.png')


def memory_chart():
    fig, ax = base_axes('1接続あたりに増えたメモリ',
                        '(放置中のRSS − 接続前のRSS) ÷ 接続数・1回の計測',
                        'KB / 接続（Pythonスレッドはスレッドあたり）')
    values = [None, 36.8, None, 0, 2.4, 8.9, 0.18]
    labels = ['対象外（300接続のため）', '36.8KB', '計測前にプロセスが落ちた',
              '≈0（計測誤差の範囲）', '2.4KB', '8.9KB', '0.18KB']
    model_bars(ax, values, labels)
    ax.set_xlim(0, 50)
    legend(fig)
    finish(fig, 'c10k-memory.png')


CPU_ROWS = [
    ('Python スレッド', 'thread'),
    ('Go OSスレッド固定', 'thread'),
    ('Python selectors', 'mux'),
    ('Python asyncio', 'mux'),
    ('Go goroutine', 'mux'),
    ('Go kqueue', 'mux'),
]


def cpu_chart():
    fig, ax = base_axes('1件ごとに1msの計算を入れたときの処理件数',
                        '64接続・5秒 × 3回（棒は中央値、細線は最小〜最大）',
                        '1秒あたりの処理件数')
    # 3回分の (件/秒, 使ったコア数)
    runs = [
        [(946, 1.09), (974, 1.09), (1037, 1.08)],
        [(5270, 6.57), (5240, 6.75), (5262, 6.71)],
        [(973, 1.00), (973, 1.00), (1011, 1.00)],
        [(1000, 1.00), (1042, 1.00), (1005, 1.00)],
        [(5448, 6.62), (5373, 6.30), (5152, 6.12)],
        [(987, 1.00), (1024, 1.00), (986, 1.00)],
    ]
    medians, labels = [], []
    for y, r in enumerate(runs):
        rps = sorted(v for v, _ in r)
        cores = sorted(c for _, c in r)
        medians.append(rps[1])
        labels.append('{:,}件/秒・{:.1f}コア'.format(rps[1], cores[1]))
        ax.plot([rps[0], rps[2]], [y, y], color=INK, linewidth=1.2, zorder=3)
    model_bars(ax, medians, labels, top_pad=1.2, rows=CPU_ROWS)
    # 値ラベルを最大値の外側に出す
    for text, r in zip(ax.texts, runs):
        text.xy = (max(v for v, _ in r), text.xy[1])
    ax.axvline(1000, color=INK_2, linestyle=(0, (4, 3)), linewidth=1, zorder=1)
    ax.annotate('1コアの上限（1ms × 1000件）', (1000, -0.85), xytext=(6, 0),
                textcoords='offset points', ha='left', va='center',
                fontsize=8.5, color=INK_2)
    ax.set_xlim(0, 8000)
    legend(fig, models=('thread', 'mux'))
    finish(fig, 'cpu-throughput.png')


def backlog_chart():
    fig, ax = plt.subplots(figsize=(8, 4.0), dpi=200)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    for side in ('top', 'right', 'left'):
        ax.spines[side].set_visible(False)
    ax.spines['bottom'].set_color(BASELINE)
    ax.tick_params(axis='x', colors=INK_2, length=0)
    ax.tick_params(axis='y', colors=MUTED, length=0)
    ax.grid(axis='y', color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)

    bursts = ['100', '128', '160', '250', '500']
    failed = [0, 0, 17, 74, 348]
    xs = range(len(bursts))
    ax.bar(xs, failed, width=0.6, color='#2a78d6', zorder=2)
    for x, f in zip(xs, failed):
        ax.annotate(str(f), (x, f), xytext=(0, 4), textcoords='offset points',
                    ha='center', fontsize=9, color=INK)
    ax.set_xticks(list(xs), bursts)
    ax.axvline(1.5, color=INK_2, linestyle=(0, (4, 3)), linewidth=1, zorder=3)
    ax.annotate('accept キューの上限 128', (1.5, 330), xytext=(-6, 0),
                textcoords='offset points', ha='right', fontsize=8.5, color=INK_2)
    ax.set_ylim(0, 390)
    ax.set_xlabel('一斉に張った接続数', color=MUTED, fontsize=9)
    ax.set_ylabel('失敗した接続数', color=MUTED, fontsize=9)
    fig.text(0.02, 0.965, '一斉接続数が accept キューの上限を超えると、溢れた分が捨てられる',
             fontsize=13, color=INK, weight='bold', va='top')
    fig.text(0.02, 0.9, 'Go goroutine サーバーに同時接続数の制限なしで接続・1回の計測',
             fontsize=9, color=INK_2, va='top')
    fig.subplots_adjust(left=0.1, right=0.96, top=0.8, bottom=0.14)
    OUT.mkdir(exist_ok=True)
    fig.savefig(OUT / 'backlog-burst.png', facecolor=SURFACE)
    plt.close(fig)
    print('wrote', OUT / 'backlog-burst.png')


if __name__ == '__main__':
    success_chart()
    threads_chart()
    memory_chart()
    cpu_chart()
    backlog_chart()
