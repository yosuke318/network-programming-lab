"""チャットのパケット形式（サーバーとクライアントで共有する約束）。

1パケット = 1メッセージ:

    +-------------+------------------------+---------------------------+
    | usernamelen |        username        |          message          |
    |   1 byte    |  usernamelen バイト      |       残りすべて           |
    +-------------+------------------------+---------------------------+
    |<------------------------ 最大 4096 バイト ------------------------->|

UDP はデータグラム単位で届くので、TCP のように区切り文字を決める必要はない。
recvfrom 1回 = パケット1つ がそのまま成り立つ。
"""

# 【機能要件2】一度に扱うメッセージは最大 4096 バイト。
# クライアントが送れる大きさも、サーバーが他クライアントへ転送する大きさもこれ。
MAX_PACKET_SIZE = 4096

# 【機能要件4】先頭 1 バイトで長さを表すので、ユーザー名は最大 255 (2**8 - 1) バイト。
MAX_USERNAME_SIZE = 2 ** 8 - 1

# 【機能要件5】バイト列は UTF-8 でエンコード / デコードする。
ENCODING = 'utf-8'


class ProtocolError(ValueError):
    """パケットが約束どおりの形をしていない。"""


def encode(username, message):
    """ユーザー名と本文を 1 パケットのバイト列にする。

    【機能要件4】先頭 1 バイト = usernamelen、続いて username、残りが message。
    【機能要件5】文字列は UTF-8 でバイト列にする（1文字 1〜4 バイト）。
    """
    username_bytes = username.encode(ENCODING)
    message_bytes = message.encode(ENCODING)

    if not 1 <= len(username_bytes) <= MAX_USERNAME_SIZE:
        raise ProtocolError('ユーザー名は 1〜{} バイトにしてください（今は {} バイト）'.format(
            MAX_USERNAME_SIZE, len(username_bytes)))

    packet = bytes([len(username_bytes)]) + username_bytes + message_bytes

    # 【機能要件2】1 パケット 4096 バイトを超えるものは送らない。
    if len(packet) > MAX_PACKET_SIZE:
        raise ProtocolError('メッセージが長すぎます（{} / {} バイト）'.format(
            len(packet), MAX_PACKET_SIZE))
    return packet


def decode(packet):
    """パケットを (username, message) に戻す。

    【機能要件4】最初の 1 バイトを読んで usernamelen を知り、
    その長さぶんをユーザー名、残りをメッセージとして取り出す。
    """
    if len(packet) > MAX_PACKET_SIZE:
        raise ProtocolError('パケットが 4096 バイトを超えています')
    if len(packet) < 1:
        raise ProtocolError('空のパケット')

    username_len = packet[0]
    if username_len == 0:
        raise ProtocolError('ユーザー名が空')
    if len(packet) < 1 + username_len:
        raise ProtocolError('usernamelen がパケットの長さより大きい')

    # 【機能要件5】UTF-8 としてデコードする。
    # ユーザー名は識別に使うので壊れていたら弾き、本文は壊れた部分を置き換えて表示する。
    try:
        username = packet[1:1 + username_len].decode(ENCODING)
    except UnicodeDecodeError as e:
        raise ProtocolError('ユーザー名が UTF-8 ではない') from e
    message = packet[1 + username_len:].decode(ENCODING, errors='replace')
    return username, message
