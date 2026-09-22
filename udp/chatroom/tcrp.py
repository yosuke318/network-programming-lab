"""TCRP（チャットルームプロトコル）: ルームの作成・参加に使う TCP 上の約束。

1 メッセージの形:

    ヘッダー（32 バイト）
    +--------------+-----------+--------+---------------------------------+
    | RoomNameSize | Operation | State  |      OperationPayloadSize       |
    |    1 byte    |  1 byte   | 1 byte |    29 bytes（ビッグエンディアン）  |
    +--------------+-----------+--------+---------------------------------+
    ボディ
    +---------------------------+-----------------------------------------+
    |  RoomName（最大 28 バイト）  |   OperationPayload（最大 229 バイト）     |
    +---------------------------+-----------------------------------------+

1 回のやり取り（トランザクション）:

    クライアント                          サーバー
        | --- State 0 リクエスト（ユーザー名など）--> |
        | <-- State 1 応答（ステータスコード）-------- |   失敗ならここで終わり
        | <-- State 2 完了（トークン）-------------- |
        |              TCP を閉じる                   |

コメントの【機能要件1.N】は課題文の「1. チャットルームの作成と接続（TCP）」の番号に対応している。
"""

import json

# 【機能要件1.2】ヘッダーは 32 バイト = 1 + 1 + 1 + 29。
HEADER_SIZE = 32
PAYLOAD_SIZE_BYTES = 29

# 【機能要件1.3】ルーム名は最大 28 バイト、ペイロードは最大 229 バイト。
MAX_ROOM_NAME_SIZE = 28
MAX_PAYLOAD_SIZE = 229

# 【機能要件1.8】トークンは最大 255 バイト（UDP 側の TokenSize が 1 バイトなので）。
# ただし TCRP のペイロードで送るので、実際には 229 バイトまでしか送れない。
MAX_TOKEN_SIZE = 255

# ユーザー名の上限（課題文には書かれていないので自分で決めた）。
# State 1 の応答にユーザー名を入れて返すことがあり、それが 229 バイトに収まるようにしている。
MAX_USERNAME_SIZE = 64

# 【機能要件1.4】ルーム名は UTF-8。
ENCODING = 'utf-8'

# 【機能要件1.5・1.9】Operation（操作コード）
OP_CREATE = 1   # 新しいチャットルームを作る
OP_JOIN = 2     # 既存のチャットルームに参加する

# 【機能要件1.5〜1.8】State（状態）
STATE_REQUEST = 0    # クライアント → サーバー: リクエスト
STATE_RESPONSE = 1   # サーバー → クライアント: ステータスコードで即答
STATE_COMPLETE = 2   # サーバー → クライアント: トークンを渡して完了

# 【機能要件1.7】State 1 で返すステータスコード（HTTP の番号を借りている）。
STATUS_OK = 200
STATUS_BAD_REQUEST = 400      # ペイロードが読めない、ユーザー名が空など
STATUS_WRONG_PASSWORD = 401   # パスワードが違う
STATUS_ROOM_NOT_FOUND = 404   # 参加しようとしたルームがない
STATUS_CONFLICT = 409         # 作ろうとしたルーム名が使われている / ルーム内でユーザー名が重複


class ProtocolError(ValueError):
    """メッセージが約束どおりの形をしていない。"""


def encode(room_name, operation, state, payload):
    """TCRP の 1 メッセージをバイト列にする。

    payload は bytes。中身の形式（JSON / 文字列）は Operation と State ごとに決める（【機能要件1.4】）。
    """
    room_bytes = room_name.encode(ENCODING)
    if len(room_bytes) > MAX_ROOM_NAME_SIZE:
        raise ProtocolError('ルーム名は {} バイトまでです（今は {} バイト）'.format(
            MAX_ROOM_NAME_SIZE, len(room_bytes)))
    if len(payload) > MAX_PAYLOAD_SIZE:
        raise ProtocolError('ペイロードは {} バイトまでです（今は {} バイト）'.format(
            MAX_PAYLOAD_SIZE, len(payload)))

    # 【機能要件1.2】RoomNameSize | Operation | State | OperationPayloadSize（29 バイトの整数）
    header = (bytes([len(room_bytes), operation, state])
              + len(payload).to_bytes(PAYLOAD_SIZE_BYTES, 'big'))
    # 【機能要件1.3】ボディ = ルーム名 + ペイロード
    return header + room_bytes + payload


def recv_exact(sock, size):
    """TCP から、ちょうど size バイトを読む。

    TCP はバイトの流れで、メッセージの区切りを持たない。1 回の recv で
    32 バイト頼んでも 10 バイトしか返ってこないことがあるので、揃うまで読み続ける。
    （UDP の recvfrom は 1 回で 1 パケットがまるごと返るので、この処理が要らなかった）
    """
    chunks = []
    remaining = size
    while remaining > 0:
        chunk = sock.recv(remaining)
        if not chunk:
            raise ProtocolError('相手が途中で接続を閉じました')
        chunks.append(chunk)
        remaining -= len(chunk)
    return b''.join(chunks)


def receive(sock):
    """TCP ソケットから TCRP の 1 メッセージを読み、(room_name, operation, state, payload) を返す。"""
    # 【機能要件1.2】まず固定長 32 バイトのヘッダーを読み、ボディの長さを知る。
    header = recv_exact(sock, HEADER_SIZE)
    room_name_size = header[0]
    operation = header[1]
    state = header[2]
    payload_size = int.from_bytes(header[3:HEADER_SIZE], 'big')

    # 【機能要件1.3】上限を超える長さを名乗っていたら、ボディを読まずに弾く。
    # （確かめないと、巨大な長さを名乗られたときに延々と読み続けてしまう）
    if room_name_size > MAX_ROOM_NAME_SIZE:
        raise ProtocolError('RoomNameSize が {} バイトを超えています'.format(MAX_ROOM_NAME_SIZE))
    if payload_size > MAX_PAYLOAD_SIZE:
        raise ProtocolError('OperationPayloadSize が {} バイトを超えています'.format(MAX_PAYLOAD_SIZE))

    body = recv_exact(sock, room_name_size + payload_size)
    # 【機能要件1.4】ルーム名は UTF-8 でデコードする。
    try:
        room_name = body[:room_name_size].decode(ENCODING)
    except UnicodeDecodeError as e:
        raise ProtocolError('ルーム名が UTF-8 ではない') from e
    payload = body[room_name_size:]
    return room_name, operation, state, payload


# --- ペイロードの中身 ----------------------------------------------------------
# 【機能要件1.4】ペイロードの形式は Operation と State ごとに変わる。
#   State 0（リクエスト）: JSON {"username": ..., "password": ...}
#   State 1（応答）      : JSON {"status": 200, "message": "..."}
#   State 2（完了）      : トークンの文字列（UTF-8）

def encode_json(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(',', ':')).encode(ENCODING)


def decode_json(payload):
    try:
        obj = json.loads(payload.decode(ENCODING))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ProtocolError('ペイロードが JSON ではない') from e
    if not isinstance(obj, dict):
        raise ProtocolError('ペイロードが JSON のオブジェクトではない')
    return obj
