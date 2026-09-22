"""ルーム内のチャットに使う UDP パケットの約束。

クライアント → サーバー（最大 4096 バイト）:

    +--------------+-----------+--------------+-----------+----------------+
    | RoomNameSize | TokenSize |   RoomName   |   Token   |    Message     |
    |    1 byte    |  1 byte   |              |           |   残りすべて     |
    +--------------+-----------+--------------+-----------+----------------+

サーバー → クライアント（最大 4094 バイト）:

    +------------------------------------------------------------------+
    | Message（ヘッダーなし）                                              |
    +------------------------------------------------------------------+

コメントの【機能要件2.N】は課題文の「2. ルームでのチャット（UDP）」の番号に対応している。
（課題文で 2 つ目の節も「1.」と書かれているので、ここでは 2 と読み替えている）
"""

import json

# 【機能要件2.4】クライアントが送るパケットは最大 4096 バイト。
MAX_REQUEST_SIZE = 4096
# 【機能要件2.5】クライアントが受け取るのは最大 4094 バイト（メッセージだけ）。
MAX_RESPONSE_SIZE = 4094

MAX_ROOM_NAME_SIZE = 28   # TCRP と同じ上限（【機能要件1.3】）
MAX_TOKEN_SIZE = 255      # 1 バイトで長さを書くので 255 まで（【機能要件1.8】）

ENCODING = 'utf-8'

# --- クライアント → サーバーの Message の決まり ----------------------------------
# Message は基本的にチャットの本文（UTF-8）。ただし次の 2 つは制御用として扱う。
#   空（0 バイト）  : 参加 / 生存確認（heartbeat）。転送しない
#   0x00 の 1 バイト: 退出。ホストが送るとルームが閉じる
# 本文を入力しても NUL（0x00）1 文字だけにはならないので、チャットとは区別できる。
HEARTBEAT = b''
LEAVE = b'\x00'


class ProtocolError(ValueError):
    """パケットが約束どおりの形をしていない。"""


def encode_request(room_name, token, message=HEARTBEAT):
    """【機能要件2.4・2.5】RoomNameSize | TokenSize | RoomName | Token | Message を組み立てる。

    message は bytes（チャット本文なら str.encode したもの、制御なら HEARTBEAT / LEAVE）。
    """
    room_bytes = room_name.encode(ENCODING)
    token_bytes = token.encode(ENCODING)
    if len(room_bytes) > MAX_ROOM_NAME_SIZE:
        raise ProtocolError('ルーム名が {} バイトを超えています'.format(MAX_ROOM_NAME_SIZE))
    if len(token_bytes) > MAX_TOKEN_SIZE:
        raise ProtocolError('トークンが {} バイトを超えています'.format(MAX_TOKEN_SIZE))

    packet = bytes([len(room_bytes), len(token_bytes)]) + room_bytes + token_bytes + message
    if len(packet) > MAX_REQUEST_SIZE:
        raise ProtocolError('メッセージが長すぎます（{} / {} バイト）'.format(
            len(packet), MAX_REQUEST_SIZE))
    return packet


def decode_request(packet):
    """クライアントからのパケットを (room_name, token, message) に分ける。message は bytes のまま。"""
    if len(packet) > MAX_REQUEST_SIZE:
        raise ProtocolError('パケットが {} バイトを超えています'.format(MAX_REQUEST_SIZE))
    if len(packet) < 2:
        raise ProtocolError('ヘッダーの 2 バイトが揃っていない')

    # 【機能要件2.4】最初の 2 バイトがルーム名とトークンの長さ。
    room_size = packet[0]
    token_size = packet[1]
    if room_size == 0 or token_size == 0:
        raise ProtocolError('ルーム名かトークンが空')
    if room_size > MAX_ROOM_NAME_SIZE:
        raise ProtocolError('ルーム名が {} バイトを超えています'.format(MAX_ROOM_NAME_SIZE))
    if token_size > MAX_TOKEN_SIZE:
        raise ProtocolError('トークンが {} バイトを超えています'.format(MAX_TOKEN_SIZE))
    if len(packet) < 2 + room_size + token_size:
        raise ProtocolError('名乗っている長さがパケットより大きい')

    body = packet[2:]
    try:
        room_name = body[:room_size].decode(ENCODING)
        token = body[room_size:room_size + token_size].decode(ENCODING)
    except UnicodeDecodeError as e:
        raise ProtocolError('ルーム名かトークンが UTF-8 ではない') from e
    message = body[room_size + token_size:]
    return room_name, token, message


# --- サーバー → クライアントの Message --------------------------------------------
# 【機能要件2.5】サーバーから届くのはヘッダーなしのメッセージだけ。
# 誰の発言か、切断の知らせかをクライアントが見分けられるよう、中身は JSON にしている。
#   {"type": "chat",       "from": "alice", "text": "こんにちは"}
#   {"type": "system",     "text": "bob が参加しました"}
#   {"type": "disconnect", "text": "60 秒間送信がなかったため切断しました"}

TYPE_CHAT = 'chat'
TYPE_SYSTEM = 'system'
TYPE_DISCONNECT = 'disconnect'


def _dump(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(',', ':')).encode(ENCODING)


def encode_event(event_type, text, sender=None):
    """サーバーからクライアントへ送る 1 メッセージを作る。

    【機能要件2.5】4094 バイトに収まらないときは text を後ろから削って収める。
    UTF-8 の 1 文字（1〜4 バイト）の途中で切らないよう、文字単位で削る。
    """
    obj = {'type': event_type, 'text': text}
    if sender is not None:
        obj['from'] = sender
    data = _dump(obj)
    while len(data) > MAX_RESPONSE_SIZE and obj['text']:
        overflow = len(data) - MAX_RESPONSE_SIZE
        # 超えたバイト数ぶん以上の文字を削る（1 文字は 1 バイト以上なので、これで必ず縮む）
        obj['text'] = obj['text'][:-max(1, overflow // 4)]
        data = _dump(obj)
    return data


def decode_event(data):
    """サーバーからのメッセージを dict に戻す。"""
    try:
        obj = json.loads(data.decode(ENCODING))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ProtocolError('サーバーからのメッセージが JSON ではない') from e
    if not isinstance(obj, dict) or 'type' not in obj:
        raise ProtocolError('サーバーからのメッセージの形が違う')
    return obj
