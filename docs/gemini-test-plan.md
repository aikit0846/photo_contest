# Gemini Test Plan

2026-03-31 更新。

対象イベント日は `2026-04-19`。
Gemini API Free tier の RPD reset は `midnight Pacific time` なので、このイベントでは日本時間 `2026-04-19 16:00 JST` に reset されます。
したがって、本番前に Gemini を温存したい境界は `2026-04-18 16:00 JST` です。

## 目的

- 本番当日に `70` 件前後の採点を安全に回せることを確認する
- `Gemini free tier` の回数制限と頻度制限を踏まえ、無駄打ちを避ける
- 途中失敗時に `force` なしで再開できることを確認する
- 本番に近いバックエンド条件で、開始端末から切り離した採点完走を確認する

## どこでテストするか

この計画は、原則として `localhost` ではなく、デプロイ済みの `Cloud Run` に対してテストする前提です。

- ブラウザで見る先:
  - ゲスト向けに採用する alias URL
  - `https://wedding-photo-contest-doef3tydea-an.a.run.app`
- `/admin` での採点実行先:
  - デプロイ済み Cloud Run
- `seed / status / cleanup` スクリプトの実行場所:
  - 手元の terminal でよい
  - ただし、環境変数は本番相当の `Firestore / GCS / APP_URL` を向いている必要がある

つまり、

- データ投入と cleanup はローカル terminal から本番相当 backend に対して行う
- UI 確認と採点実行はデプロイ済み Cloud Run の画面で行う
- 印刷済み QR を前提にした guest 導線 E2E では、canonical URL ではなく次の alias URL を入口として使う:
  - `https://wedding-photo-contest-doef3tydea-an.a.run.app/entry`

先行確認メモ:

- alias URL `https://wedding-photo-contest-doef3tydea-an.a.run.app/entry` からの guest 導線 E2E は通っている
- テストユーザで
  - 投稿
  - 差し替え
  - `/admin` で投稿確認
  - 締切
  - `gemini-2.5-flash` 採点
  - `/presentation`
  - フィードバック公開
  - guest 側確認
 まで問題なさそう

## この計画の前提

- UI 導線確認と Gemini 負荷確認は分ける
- UI 導線確認は少人数 + `mock` で行う
- 70 人規模テストは [load_test_dataset.py](/Users/taikisuzuki/wedding/photo_contest/scripts/load_test_dataset.py) を使って一括生成する
- 負荷テスト用スクリプトは backend 直書きなので、`/entry` の UI 導線そのものは通らない
- その代わり、採点の完走性、途中再開、cleanup の確実性を現実的に検証できる
- 現在の採点は `Cloud Tasks + judging job` 前提
- 採点開始は iPhone からでもよく、その後の task 実行は Cloud Tasks が進める
- MacBook Air では `/admin` を開いて進捗確認と結果確認を行う

## 事前ルール

- `2026-04-18 16:00 JST` 以降は Gemini の新規テストを止める
- 70 件の Gemini テストは、同じ日に何回も繰り返さない
- UI / CSS / presentation の確認は Gemini を使わず `mock` で行う
- 本番に近いテスト日は、iPhone で開始しても MacBook から進捗確認できることを確認する
- `2026-04-12` と `2026-04-17` は Cloud Tasks 経由の e2e として実施する

## テスト全体像

### テスト A: UI / 導線の確認

- provider:
  - `mock`
- 規模:
  - 少人数
- 確認したいもの:
  - 印刷済み QR の alias URL `https://wedding-photo-contest-doef3tydea-an.a.run.app/entry`
  - カテゴリ選択
  - 名前選択
  - 投稿
  - 差し替え
  - `/presentation`

### テスト B: 採点完走性の確認

- provider:
  - `gemini-2.5-flash`
- 規模:
  - `70` 件
- 確認したいもの:
  - 最後まで回し切れるか
  - 開始端末を閉じても継続するか
  - MacBook で進捗確認できるか
  - Free tier の RPM / RPD で破綻しないか

### テスト C: コメント品質の確認

- provider:
  - `gemini-2.5-flash`
- 規模:
  - `10` から `20` 件
- 確認したいもの:
  - 実写真っぽい入力でコメントが破綻しないか
  - 文体とトーンが許容か

## 毎回の実行前チェック

0. テスト用 terminal に本番相当 backend の環境変数を設定する。

```bash
export PROJECT_ID=wedding-photo-contest-20260419
export REGION=asia-northeast1
export SERVICE_NAME=wedding-photo-contest
export DATA_BACKEND=firestore
export STORAGE_BACKEND=gcs
export FIRESTORE_PROJECT="$PROJECT_ID"
export FIRESTORE_DATABASE='(default)'
export GCS_BUCKET=wedding-photo-contest-20260419-assets
export CLOUD_TASKS_PROJECT="$PROJECT_ID"
export CLOUD_TASKS_LOCATION="$REGION"
export CLOUD_TASKS_QUEUE=judging-jobs
gcloud config set project "$PROJECT_ID"
gcloud config set run/region "$REGION"
export APP_URL="https://wedding-photo-contest-doef3tydea-an.a.run.app"
```

もし `gcloud run services describe ...` で認証エラーが出るときは、先に local 認証を更新する。

```bash
gcloud auth login
gcloud auth application-default login
gcloud auth application-default set-quota-project "$PROJECT_ID"
gcloud config set project "$PROJECT_ID"
gcloud config set run/region "$REGION"
```

補足:

- `gcloud auth login`
  - `gcloud` CLI 自体の認証
- `gcloud auth application-default login`
  - local の Python スクリプトが Firestore / GCS を触るための認証
- `gcloud auth application-default set-quota-project "$PROJECT_ID"`
  - quota project mismatch 警告を解消するための設定

1. 本番相当 backend を向いていることを確認する。

```bash
echo "$DATA_BACKEND"
echo "$STORAGE_BACKEND"
echo "$FIRESTORE_PROJECT"
echo "$GCS_BUCKET"
echo "$APP_URL"
```

期待値の例:

- `DATA_BACKEND=firestore`
- `STORAGE_BACKEND=gcs`
- `FIRESTORE_PROJECT=wedding-photo-contest-20260419`
- `FIRESTORE_DATABASE=(default)`
- `GCS_BUCKET=wedding-photo-contest-20260419-assets`
- `APP_URL=https://wedding-photo-contest-doef3tydea-an.a.run.app`

2. Cloud Run の実 URL が想定どおりか確認する。

```bash
gcloud run services describe wedding-photo-contest \
  --project wedding-photo-contest-20260419 \
  --region asia-northeast1 \
  --format='value(status.url)'
```

3. テストで使う管理画面の URL を確認する。

```text
ブラウザで開く:
$APP_URL/admin
```

4. 非テスト submission が 0 件であることを確認する。

```text
ブラウザ操作:
1. $APP_URL/admin を開く
2. 投稿数 と 採点済み を確認する
3. 本番 guest 由来の submission が 0 件であることを確認する
```

5. safety guard の前提を理解する。

```text
補足:
load_test_dataset.py は、非テスト submission が 1 件でも残っていると seed を abort する
```

6. Cloud Tasks 設定が本番相当で入っていることを確認する。

```bash
echo "$CLOUD_TASKS_PROJECT"
echo "$CLOUD_TASKS_LOCATION"
echo "$CLOUD_TASKS_QUEUE"
```

期待値の例:

- `CLOUD_TASKS_PROJECT=wedding-photo-contest-20260419`
- `CLOUD_TASKS_LOCATION=asia-northeast1`
- `CLOUD_TASKS_QUEUE=judging-jobs`

7. Cloud Tasks queue が存在することを確認する。

```bash
gcloud tasks queues describe judging-jobs \
  --location=asia-northeast1 \
  --project=wedding-photo-contest-20260419
```

## 日別テスト計画

### 2026-03-29: スクリプト sanity check

ステータス:

- 完了

目的:

- 一括投入 / status / cleanup の流れが壊れていないことを確認する
- Gemini は使わない

手順:

1. `/admin` で非テスト submission が 0 件であることを確認する。

```text
ブラウザ操作:
1. $APP_URL/admin を開く
2. 本番 guest の投稿がまだ 0 件であることを確認する
```

2. 12 件だけテストデータを投入する。

```bash
uv run python scripts/load_test_dataset.py seed --tag 2026-03-29-sanity --count 12
```

3. 投入結果を確認する。

```bash
uv run python scripts/load_test_dataset.py status --tag 2026-03-29-sanity
```

4. デプロイ済み admin を開く。

```text
ブラウザで開く:
$APP_URL/admin
```

5. provider を `mock` にして採点する。

```text
ブラウザ操作:
1. Provider を mock にする
2. AI 採点を実行 を押す
3. 進捗が最後まで進むことを確認する
```

6. 採点後の状態を確認する。

```bash
uv run python scripts/load_test_dataset.py status --tag 2026-03-29-sanity
```

7. テストデータを削除する。

```bash
uv run python scripts/load_test_dataset.py cleanup --tag 2026-03-29-sanity --yes
```

8. cleanup 後に、テストデータが 0 件に戻ったことを確認する。

```bash
uv run python scripts/load_test_dataset.py status --tag 2026-03-29-sanity
```

使用する Gemini request:

- `0`

実施結果:

- Cloud Tasks + job 方式での最小 sanity check は完了
- `12件 + mock` では進捗表示が出る前に完了することがあった
- この規模では表示が見えないこと自体は想定内と判断

### 2026-03-31: 70 件 mock rehearsal

ステータス:

- 完了
- `2026-03-31` 枠の rehearsal は前倒しで実施済み

目的:

- 70 件規模の guest / submission / cleanup が問題ないことを確認する
- admin 画面の進捗表示が破綻しないことを確認する
- Gemini はまだ使わない

手順:

1. `/admin` で非テスト submission が 0 件であることを確認する。

```text
ブラウザ操作:
1. $APP_URL/admin を開く
2. 本番 guest の投稿がまだ 0 件であることを確認する
```

2. 70 件のテストデータを投入する。

```bash
uv run python scripts/load_test_dataset.py seed --tag 2026-03-31-mock70 --count 70
```

3. 投入結果を確認する。

```bash
uv run python scripts/load_test_dataset.py status --tag 2026-03-31-mock70
```

4. デプロイ済み admin を開く。

```text
ブラウザで開く:
$APP_URL/admin
```

5. provider を `mock` にして採点する。

```text
ブラウザ操作:
1. Provider を mock にする
2. AI 採点を実行 を押す
3. 進捗が 70/70 まで進むことを確認する
```

6. 採点後の状態を確認する。

```bash
uv run python scripts/load_test_dataset.py status --tag 2026-03-31-mock70
```

7. テストデータを削除する。

```bash
uv run python scripts/load_test_dataset.py cleanup --tag 2026-03-31-mock70 --yes
```

8. cleanup 後に、テストデータが 0 件に戻ったことを確認する。

```bash
uv run python scripts/load_test_dataset.py status --tag 2026-03-31-mock70
```

使用する Gemini request:

- `0`

実施結果:

- PC から採点開始するパターンを確認した
- iPhone から採点開始するパターンも確認した
- iPhone は採点開始直後に画面ロック、PC も閉じた状態で継続した
- しばらく待ってから PC を開き直し、画面更新すると結果が反映されていた
- Cloud Tasks + job 方式で、開始端末から切り離した mock 採点が成立することを確認できた

### 2026-04-05: 70 件 Gemini full run 1 回目

ステータス:

- 完了
- `2026-04-05` 枠の rehearsal は前倒しで実施済み

目的:

- 70 件規模の Gemini 採点が完走するかを確認する
- 本番相当の最重要 rehearsal

実施ルール:

- 当日は Gemini の他テストを極力入れない
- この 70 件 run を最優先にする

手順:

1. `/admin` で非テスト submission が 0 件であることを確認する。

```text
ブラウザ操作:
1. $APP_URL/admin を開く
2. 本番 guest の投稿がまだ 0 件であることを確認する
```

2. 70 件のテストデータを投入する。

```bash
uv run python scripts/load_test_dataset.py seed --tag 2026-04-05-gemini70-a --count 70
```

3. 投入結果を確認する。

```bash
uv run python scripts/load_test_dataset.py status --tag 2026-04-05-gemini70-a
```

4. デプロイ済み admin を開く。

```text
ブラウザで開く:
$APP_URL/admin
```

5. Gemini で全件採点を開始する。

```text
ブラウザ操作:
1. Provider を auto か gemini にする
2. Model hint を gemini-2.5-flash にする
3. AI 採点を実行 を押す
4. admin ページを閉じずに最後まで待つ
```

6. 採点後の状態を確認する。

```bash
uv run python scripts/load_test_dataset.py status --tag 2026-04-05-gemini70-a
```

7. テストデータを削除する。

```bash
uv run python scripts/load_test_dataset.py cleanup --tag 2026-04-05-gemini70-a --yes
```

8. cleanup 後に、テストデータが 0 件に戻ったことを確認する。

```bash
uv run python scripts/load_test_dataset.py status --tag 2026-04-05-gemini70-a
```

確認ポイント:

- `judged=70` に到達するか
- `failed` が 0 か、数件で再実行復旧できるか
- 所要時間が `15〜20分` に収まるか

使用する Gemini request の目安:

- `70`

実施結果:

- デプロイ済み Cloud Run で `70` 件の Gemini 採点が完走した
- 今回は無事動作した
- 所要時間はおよそ `16〜17分`
- 現時点では本番許容の `15〜20分` に収まっている
- この時点では Cloud Tasks + job 方式ではなく、旧方式での確認

### 2026-04-10: 実写真ベースの品質テスト

ステータス:

- 完了

目的:

- コメントのトーンと破綻を確認する
- インフラ負荷ではなく品質確認日

準備:

- `./tmp/test-photos` に実写真 `10` から `20` 枚程度を置く
- 著作権や取り扱いに問題ない写真だけ使う

手順:

1. `/admin` で非テスト submission が 0 件であることを確認する。

```text
ブラウザ操作:
1. $APP_URL/admin を開く
2. 本番 guest の投稿がまだ 0 件であることを確認する
```

2. 実写真を使った 20 件テストデータを投入する。

```bash
uv run python scripts/load_test_dataset.py seed \
  --tag 2026-04-10-real20 \
  --count 20 \
  --source-dir ./tmp/test-photos
```

3. 投入結果を確認する。

```bash
uv run python scripts/load_test_dataset.py status --tag 2026-04-10-real20
```

4. デプロイ済み admin を開く。

```text
ブラウザで開く:
$APP_URL/admin
```

5. Gemini で採点する。

```text
ブラウザ操作:
1. Provider を auto か gemini にする
2. Model hint を gemini-2.5-flash にする
3. AI 採点を実行 を押す
4. コメント品質を見る
```

6. テストデータを削除する。

```bash
uv run python scripts/load_test_dataset.py cleanup --tag 2026-04-10-real20 --yes
```

7. cleanup 後に、テストデータが 0 件に戻ったことを確認する。

```bash
uv run python scripts/load_test_dataset.py status --tag 2026-04-10-real20
```

使用する Gemini request の目安:

- `20`

実施結果:

- 点数の品質はよい感じ
- コメントの品質もよい感じ
- 採点処理は問題なく動作した

### 2026-04-12: 70 件 Gemini recovery test

ステータス:

- 完了

目的:

- Cloud Tasks + job 方式で、部分失敗や queue 停止から回復できるか確認する
- ブラウザ中断耐性ではなく、サーバジョブの recovery を確認する
- 本番前の最重要 worst-case rehearsal

先行確認メモ:

- iPhone 12 の Chrome から採点開始して、すぐ画面ロックして 10 分程度放置しても、backend 側の採点自体は継続した
- 最終的に `70` 件すべて完了した
- 所要時間は `15分弱`
- したがって、次の主眼は「ブラウザを閉じても動くか」ではなく「queue pause/resume や partial failure から回復できるか」に置く

手順:

1. `/admin` で非テスト submission が 0 件であることを確認する。

```text
ブラウザ操作:
1. $APP_URL/admin を開く
2. 本番 guest の投稿がまだ 0 件であることを確認する
```

2. 70 件のテストデータを投入する。

```bash
uv run python scripts/load_test_dataset.py seed --tag 2026-04-12-gemini70-recovery --count 70
```

3. 投入結果を確認する。

```bash
uv run python scripts/load_test_dataset.py status --tag 2026-04-12-gemini70-recovery
```

4. iPhone で admin を開く。

```text
ブラウザで開く:
iPhone Safari で $APP_URL/admin
```

5. iPhone で Gemini 採点を開始する。

```text
ブラウザ操作:
1. Provider を auto か gemini にする
2. Model hint を gemini-2.5-flash にする
3. AI 採点を実行 を押す
4. 採点ジョブが開始されたら、その場で iPhone は閉じるか別画面へ移ってよい
```

6. MacBook Air で admin を開き、進捗確認する。

```text
ブラウザ操作:
1. MacBook Air で $APP_URL/admin を開く
2. 途中まで進むことを確認する
3. この時点ではまだ完走させない
```

7. Cloud Shell から queue を一時停止する。

```bash
gcloud tasks queues pause judging-jobs \
  --location=asia-northeast1 \
  --project=wedding-photo-contest-20260419
```

8. 数分待って、採点件数がそれ以上進まないことを確認する。

```text
ブラウザ操作:
1. MacBook Air の $APP_URL/admin を見る
2. 必要ならタブを更新して、採点済み件数が止まっていることを確認する
```

9. queue を再開する。

```bash
gcloud tasks queues resume judging-jobs \
  --location=asia-northeast1 \
  --project=wedding-photo-contest-20260419
```

10. しばらく待って、採点が再開することを確認する。

```text
ブラウザ操作:
1. MacBook Air の $APP_URL/admin を見る
2. 必要ならタブを更新して、採点済み件数が再び増え始めることを確認する
3. 最終的に 70 件が完走することを確認する
```

11. 採点後の状態を確認する。

```bash
uv run python scripts/load_test_dataset.py status --tag 2026-04-12-gemini70-recovery
```

12. テストデータを削除する。

```bash
uv run python scripts/load_test_dataset.py cleanup --tag 2026-04-12-gemini70-recovery --yes
```

13. cleanup 後に、テストデータが 0 件に戻ったことを確認する。

```bash
uv run python scripts/load_test_dataset.py status --tag 2026-04-12-gemini70-recovery
```

使用する Gemini request の目安:

- `70` 前後

確認ポイント:

- queue pause 中に件数が止まるか
- queue resume 後に件数が再び増えるか
- `70` 件が最後まで完走するか
- Cloud Tasks + job 化によって所要時間が大きく悪化していないか
- worst-case 操作を入れても `force` なしで自然復帰するか

実施結果:

- iPhone から採点開始して、タブを落としたり MacBook から開いて閉じたりしても想定どおり動いた
- queue の pause / resume を挟んでも想定どおり回復した
- worst-case 操作まで含めて、Cloud Tasks + job 方式は期待どおりの挙動を確認できた

### 2026-04-17: 最終 Gemini smoke test

目的:

- 本番直前の軽い確認
- ここでは 70 件は回さない

先行確認メモ:

- `10` 件の Gemini テストで、iPhone の Chrome から採点開始してすぐ画面ロックしても、前回の失敗系 UI は再現しなかった
- iPhone 側では進捗表示が出ることを確認できた
- 一方で、MacBook Air 側はタブを更新しないと進捗表示や採点完了数が更新されない事象が残っている
- したがって、この smoke test の主眼は「開始端末の UX が改善したか」と「監視端末の自動更新がまだ弱いか」の確認に置く

手順:

1. `/admin` で非テスト submission が 0 件であることを確認する。

```text
ブラウザ操作:
1. $APP_URL/admin を開く
2. 本番 guest の投稿がまだ 0 件であることを確認する
```

2. 10 件のテストデータを投入する。

```bash
uv run python scripts/load_test_dataset.py seed --tag 2026-04-17-smoke10 --count 10
```

3. 投入結果を確認する。

```bash
uv run python scripts/load_test_dataset.py status --tag 2026-04-17-smoke10
```

4. iPhone で admin を開く。

```text
ブラウザで開く:
iPhone Safari で $APP_URL/admin
```

5. iPhone で Gemini 採点を開始する。

```text
ブラウザ操作:
1. Provider を auto か gemini にする
2. Model hint を gemini-2.5-flash にする
3. AI 採点を実行 を押す
4. 採点開始後、iPhone は閉じてよい
```

6. MacBook Air で admin を開いて完了確認する。

```text
ブラウザ操作:
1. MacBook Air で $APP_URL/admin を開く
2. 進捗または完了結果が見えることを確認する
3. 10/10 まで完了を確認する
```

7. テストデータを削除する。

```bash
uv run python scripts/load_test_dataset.py cleanup --tag 2026-04-17-smoke10 --yes
```

8. cleanup 後に、テストデータが 0 件に戻ったことを確認する。

```bash
uv run python scripts/load_test_dataset.py status --tag 2026-04-17-smoke10
```

使用する Gemini request の目安:

- `10`

### 2026-04-18 16:00 JST 以降: Gemini freeze

ルール:

1. 新しい Gemini テストを止める。

```text
ブラウザ操作・コマンドなし:
Gemini を使うテストはここで終了する
```

2. UI 確認は `mock` だけにする。

```text
ブラウザ操作:
Provider を mock にして確認する
```

3. 実プロジェクター確認では Gemini を使わない。

```text
ブラウザ操作:
presentation 確認だけ行い、AI 採点は実行しない
```

### 2026-04-19: 本番日

本番前の手順:

1. AI Studio の active limits を確認する。

```text
ブラウザで開く:
https://aistudio.google.com/
```

2. admin を開く。

```text
ブラウザで開く:
$APP_URL/admin
```

3. provider と model を確認する。

```text
ブラウザ操作:
1. Provider が auto または gemini になっているか確認する
2. Model hint が gemini-2.5-flash になっているか確認する
```

4. 採点中に admin を開いたままにできる端末と回線を確保する。

```text
操作メモ:
iPhone は開始だけ押せればよい
MacBook Air で admin を開いて進捗確認と結果確認を行う
```

本番中の方針:

- Gemini の全件採点は `1 回` を基本にする
- 可能なら iPhone で採点開始し、MacBook Air で進捗確認する
- 数件だけ failed の場合は `force` なしで再実行する
- 順位の最終調整は `点数補正` で行う
- 全件再採点はしない

## Gemini 消費予算の目安

この計画での Gemini request 数の目安:

- `2026-04-05`: `70`
- `2026-04-10`: `20`
- `2026-04-12`: `70`
- `2026-04-17`: `10`
- 合計: `170`

これなら各日とも `250 RPD` を大きく下回る。
ただし project 単位で消費するため、同じ日に別テストを重ねない。

## 失敗時の判断ルール

### 2026-04-05 の 70 件 run が通らなかった場合

- `2026-04-10` の品質テストは縮小してよい
- 優先順位は品質より完走性
- 先に原因を切り分ける

補足:

- この項目は今回クリア済み
- `2026-04-10` の品質確認も今回クリア済み
- 次の重点は `2026-04-12` の recovery test と `2026-04-17` の smoke test

### 2026-04-12 の recovery test が安定しなかった場合

- 本番では Gemini を主にせず、`mock` + 手動補正の比重を上げる
- それでも Gemini を使うなら、paid tier を再検討する

### 2026-04-17 の smoke で不安が残った場合

- `2026-04-18 16:00 JST` 以降は Gemini を触らない
- 本番は `mock` を fallback 第一候補にする

## この計画で確認できること / できないこと

確認できること:

- 70 件規模の採点完走性
- 途中中断からの再開
- admin 進捗表示
- 一括 cleanup の確実性
- Gemini コメントのざっくりした品質

確認できないこと:

- 本物の 70 人が同時に投稿する UI 体験
- 端末差やブラウザ差の投稿挙動
- 完全に同じ構図・同じ種類の実写真だけが大量に来たときの品質揺れ

UI 導線の最終確認は、別途少人数の実機 rehearsal で補う。
