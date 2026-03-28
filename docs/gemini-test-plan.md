# Gemini Test Plan

2026-03-28 作成。

対象イベント日は `2026-04-19`。
Gemini API Free tier の RPD reset は `midnight Pacific time` なので、このイベントでは日本時間 `2026-04-19 16:00 JST` に reset されます。
したがって、本番前に温存したい境界は `2026-04-18 16:00 JST` です。

## 目的

- 本番当日に `70` 件前後の採点を安全に回せることを確認する
- `Gemini free tier` の回数制限と頻度制限を踏まえ、無駄打ちを避ける
- 途中失敗時に `force` なしで再開できることを確認する
- 本番に近いバックエンド条件で、admin 画面からの採点完走を確認する

## この計画の前提

- UI 導線確認と Gemini 負荷確認は分ける
- UI 導線確認は少人数 + `mock` で行う
- 70 人規模テストは [load_test_dataset.py](/Users/taikisuzuki/wedding/photo_contest/scripts/load_test_dataset.py) を使って一括生成する
- 負荷テスト用スクリプトは backend 直書きなので、`/entry` の UI 導線そのものは通らない
- その代わり、採点の完走性、途中再開、cleanup の確実性を現実的に検証できる

## 事前ルール

- `2026-04-18 16:00 JST` 以降は Gemini の新規テストを止める
- 70 件の Gemini テストは、同じ日に何回も繰り返さない
- UI / CSS / presentation の確認は Gemini を使わず `mock` で行う
- 本番に近いテスト日は、admin ページを開いたままにして進捗表示を最後まで見る
- 途中で止まったら、`force` を付けずにもう一度実行して `pending / failed` を拾い直す

## テスト全体像

### テスト A: UI / 導線の確認

- 目的:
  - `/entry`
  - カテゴリ選択
  - 名前選択
  - 投稿
  - 差し替え
  - `/presentation`
- provider:
  - `mock`
- 規模:
  - 少人数で十分

### テスト B: 採点完走性の確認

- 目的:
  - 70 件前後の採点を最後まで回し切れるか
  - 途中停止から `force` なしで再開できるか
  - Gemini free tier の RPM / RPD で破綻しないか
- provider:
  - `gemini-2.5-flash`
- 規模:
  - `70` 件

### テスト C: コメント品質の確認

- 目的:
  - 実写真っぽい入力でコメントが破綻しないか
  - 文体とトーンが許容か
- provider:
  - `gemini-2.5-flash`
- 規模:
  - `10` から `20` 件で十分

## 実行前チェック

本番バックエンド向けにテストするときは、まず同じ terminal で値を確認する。

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
- `GCS_BUCKET=wedding-photo-contest-20260419-assets`
- `APP_URL=https://wedding-photo-contest-228664142250.asia-northeast1.run.app`

`APP_URL` の確認だけしたいとき:

```bash
gcloud run services describe wedding-photo-contest \
  --region asia-northeast1 \
  --format='value(status.url)'
```

## 日別テスト計画

### 2026-03-29: スクリプト sanity check

目的:

- 一括投入 / status / cleanup の流れが壊れていないことを確認する
- Gemini は使わない

手順:

1. test dataset を 12 件だけ投入する
2. `mock` で採点する
3. cleanup まで通す

コマンド:

```bash
uv run python scripts/load_test_dataset.py seed --tag 2026-03-29-sanity --count 12
uv run python scripts/load_test_dataset.py status --tag 2026-03-29-sanity
```

その後 `/admin` で:

1. provider を `mock` にする
2. `AI 採点を実行` を押す
3. 進捗が最後まで進むことを確認する

最後に:

```bash
uv run python scripts/load_test_dataset.py status --tag 2026-03-29-sanity
uv run python scripts/load_test_dataset.py cleanup --tag 2026-03-29-sanity --yes
```

使用する Gemini request:

- `0`

### 2026-03-31: 70 件 mock rehearsal

目的:

- 70 件規模の guest / submission / cleanup が問題ないことを確認する
- admin 画面の進捗表示が破綻しないことを確認する
- Gemini はまだ使わない

コマンド:

```bash
uv run python scripts/load_test_dataset.py seed --tag 2026-03-31-mock70 --count 70
uv run python scripts/load_test_dataset.py status --tag 2026-03-31-mock70
```

その後 `/admin` で:

1. provider を `mock` にする
2. `AI 採点を実行` を押す
3. 進捗が `70/70` まで進むことを確認する

最後に:

```bash
uv run python scripts/load_test_dataset.py status --tag 2026-03-31-mock70
uv run python scripts/load_test_dataset.py cleanup --tag 2026-03-31-mock70 --yes
```

使用する Gemini request:

- `0`

### 2026-04-05: 70 件 Gemini full run 1 回目

目的:

- 70 件規模の Gemini 採点が完走するかを確認する
- 本番相当の最重要 rehearsal

実施ルール:

- 当日は Gemini の他テストを極力入れない
- この 70 件 run を最優先にする

コマンド:

```bash
uv run python scripts/load_test_dataset.py seed --tag 2026-04-05-gemini70-a --count 70
uv run python scripts/load_test_dataset.py status --tag 2026-04-05-gemini70-a
```

その後 `/admin` で:

1. provider を `auto` か `gemini` にする
2. model hint を `gemini-2.5-flash` にする
3. `AI 採点を実行` を押す
4. admin ページを閉じずに最後まで待つ

終了後:

```bash
uv run python scripts/load_test_dataset.py status --tag 2026-04-05-gemini70-a
```

確認ポイント:

- `judged=70` に到達するか
- `failed` が 0 か、数件で再実行復旧できるか
- 所要時間が `15〜20分` に収まるか

cleanup:

```bash
uv run python scripts/load_test_dataset.py cleanup --tag 2026-04-05-gemini70-a --yes
```

使用する Gemini request の目安:

- `70`

### 2026-04-10: 実写真ベースの品質テスト

目的:

- コメントのトーンと破綻を確認する
- インフラ負荷ではなく品質確認日

準備:

- `./tmp/test-photos` に実写真 `10` から `20` 枚程度を置く
- 著作権や取り扱いに問題ない写真だけ使う

コマンド:

```bash
uv run python scripts/load_test_dataset.py seed --tag 2026-04-10-real20 --count 20 --source-dir ./tmp/test-photos
uv run python scripts/load_test_dataset.py status --tag 2026-04-10-real20
```

その後 `/admin` で:

1. provider を `auto` か `gemini` にする
2. model hint を `gemini-2.5-flash` にする
3. `AI 採点を実行` を押す
4. コメント品質を見る

cleanup:

```bash
uv run python scripts/load_test_dataset.py cleanup --tag 2026-04-10-real20 --yes
```

使用する Gemini request の目安:

- `20`

### 2026-04-12: 70 件 Gemini recovery test

目的:

- 途中中断からの復旧を確認する
- 本番前の最重要リカバリ rehearsal

コマンド:

```bash
uv run python scripts/load_test_dataset.py seed --tag 2026-04-12-gemini70-recovery --count 70
uv run python scripts/load_test_dataset.py status --tag 2026-04-12-gemini70-recovery
```

その後 `/admin` で:

1. provider を `auto` か `gemini` にする
2. model hint を `gemini-2.5-flash` にする
3. `AI 採点を実行` を押す
4. 進捗が `15` から `30` 件程度まで進んだら、意図的にページを reload するか閉じる
5. もう一度 `/admin` を開く
6. `force` を付けずに `AI 採点を実行` を押す
7. 最後まで完走するか確認する

終了後:

```bash
uv run python scripts/load_test_dataset.py status --tag 2026-04-12-gemini70-recovery
```

cleanup:

```bash
uv run python scripts/load_test_dataset.py cleanup --tag 2026-04-12-gemini70-recovery --yes
```

使用する Gemini request の目安:

- `70` 前後
- 中断タイミング次第で少し増えるが、同日の追加テストは入れない

### 2026-04-17: 最終 Gemini smoke test

目的:

- 本番直前の軽い確認
- ここでは 70 件は回さない

コマンド:

```bash
uv run python scripts/load_test_dataset.py seed --tag 2026-04-17-smoke10 --count 10
uv run python scripts/load_test_dataset.py status --tag 2026-04-17-smoke10
```

その後 `/admin` で:

1. provider を `auto` か `gemini` にする
2. model hint を `gemini-2.5-flash` にする
3. `AI 採点を実行` を押す
4. `10/10` まで完了を確認する

cleanup:

```bash
uv run python scripts/load_test_dataset.py cleanup --tag 2026-04-17-smoke10 --yes
```

使用する Gemini request の目安:

- `10`

### 2026-04-18 16:00 JST 以降: Gemini freeze

ルール:

- 新しい Gemini テストをしない
- UI 確認は `mock` だけにする
- 実プロジェクター確認は Gemini を使わない

### 2026-04-19: 本番日

本番前に 1 回だけ確認すること:

1. AI Studio で active limits を確認する
2. provider が `auto` または `gemini` になっているか見る
3. model hint が `gemini-2.5-flash` になっているか見る
4. admin ページを採点中ずっと開ける端末と回線を確保する

本番中の方針:

- Gemini の全件採点は `1 回` を基本にする
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
