// calc.proto を実行時に読み込み、Python の gRPC サーバーの関数を呼ぶクライアント。
// Python 側は .proto からコードを生成したが、Node.js 側は生成せずに同じ .proto を直接読む。
const path = require('node:path');
const grpc = require('@grpc/grpc-js');
const protoLoader = require('@grpc/proto-loader');

const PROTO_PATH = path.join(__dirname, '..', 'proto', 'calc.proto');

const definition = protoLoader.loadSync(PROTO_PATH, {
  keepCase: true, // str_arr を strArr に変換せず、.proto の名前のまま使う
  longs: Number, // int64 を JS の number で受け取る（既定では桁あふれ対策の Long オブジェクトになる）
  // proto3 は初期値（false, 0, 空文字）を通信に載せない。受け取った側で補わないと undefined になる。
  defaults: true,
});
const calc = grpc.loadPackageDefinition(definition).calc;

// サーバーと同じ UNIX ドメインソケットに繋ぐ。
const client = new calc.Calculator('unix:/tmp/calc.sock', grpc.credentials.createInsecure());

// grpc-js はコールバック形式なので、await で書けるよう Promise に包む。
function call(method, request) {
  return new Promise((resolve, reject) => {
    client[method](request, (err, reply) => (err ? reject(err) : resolve(reply)));
  });
}

async function main() {
  const cases = [
    ['Subtract', { a: 42, b: 23 }],
    ['Floor', { x: 3.7 }],
    ['Floor', { x: -3.2 }],
    ['Nroot', { n: 3, x: 27 }],
    ['Nroot', { n: 3, x: 64 }], // 浮動小数点の誤差がそのまま届く例
    ['Nroot', { n: 3, x: -8 }],
    ['Reverse', { s: 'hello' }],
    ['ValidAnagram', { str1: 'listen', str2: 'silent' }],
    ['ValidAnagram', { str1: 'hello', str2: 'world' }],
    ['Sort', { str_arr: ['banana', 'apple', 'cherry'] }],
    ['Nroot', { n: 0, x: 8 }], // サーバーがエラーを返す例
  ];

  for (const [method, request] of cases) {
    const shown = `${method}(${JSON.stringify(request)})`;
    try {
      const reply = await call(method, request);
      console.log(`${shown} -> ${JSON.stringify(reply.result)}`);
    } catch (err) {
      console.log(`${shown} -> エラー ${grpc.status[err.code]}: ${err.details}`);
    }
  }

  // 1本の接続で5件を同時に投げる。返事の順番がばらばらでも、どれがどのリクエストの結果かは
  // gRPC が対応づけるので、本の JSON 版のように自分で id を振って照合する必要がない。
  const replies = await Promise.all(
    [1, 2, 3, 4, 5].map((i) => call('Subtract', { a: i * 10, b: i })),
  );
  console.log(`同時に5件: ${JSON.stringify(replies.map((r) => r.result))}`);

  client.close();
}

main();
