"""③ I/O多重化（asyncio）の行エコーサーバー。

中身は select_loop.py と同じイベントループ（macOS なら kqueue）で、スレッドは1本だけ。
それでも await のおかげで、①②と同じ「1接続ずつ上から下へ」の書き方に戻っている。

※ ファイル名を asyncio.py にすると標準ライブラリを上書きしてしまうので避けている。
"""

import asyncio
import os

import work

PORT = 9103


async def handle(reader, writer):
    try:
        # データが来るまで待つ間、イベントループは他の接続の処理に回る。
        while line := await reader.readline():
            # await の無い計算はイベントループを止める。その間、他の接続は処理されない。
            work.burn()
            writer.write(line)
            await writer.drain()
    except OSError:
        pass
    finally:
        writer.close()


async def main():
    server = await asyncio.start_server(handle, '127.0.0.1', PORT, backlog=128)
    print('asyncio server on 127.0.0.1:{} pid={}'.format(PORT, os.getpid()), flush=True)
    async with server:
        await server.serve_forever()


if __name__ == '__main__':
    asyncio.run(main())
