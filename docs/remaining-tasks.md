# Wedding Photo Contest Remaining Tasks

2026-03-15 時点の残タスク整理です。

## 現在地

- Cloud Run service `wedding-photo-contest` への再デプロイは実施済み
- Cloud Run URL:
  - `https://wedding-photo-contest-228664142250.asia-northeast1.run.app`
- `GOOGLE_API_KEY` は設定済み
- `ANTHROPIC_API_KEY` は未設定
- 本番用ゲストとテストユーザーの登録は完了
- AI 方針:
  - 本番では外部 AI を入れる
  - まずは Gemini の free tier 内で最も良い stable モデルを使う方針
  - 現時点の第一候補は `gemini-2.5-flash`
  - Gemini は Cloud Run で動作確認済み
- `/admin` は Cloud Run 上でアクセス可能
  - Basic 認証あり
- `/presentation` は Cloud Run 上でアクセス可能
- `/health` は Cloud Run 上で `ok` を確認済み
- `/healthz` は Cloud Run 上で 404
  - 原因判明: Cloud Run の既知制約で、`/healthz` のような一部予約パスは外部 URL で使えない
  - 対応済み: Cloud Run 上の疎通確認は `/health` に統一した
  - コード側ではローカル互換のため `/healthz` も残している

## デプロイ済み環境で追加確認した不具合

- 確認端末 / ブラウザ:
  - `MacBook Air M2`
  - `Arc`
  - Cloud Run のデプロイ済み URL

- ローカル起動 + `MacBook Air M2 + Arc` では再現しない
- `iPhone` では少なくともゲスト UI の大崩れは起きていない
- 原因判明:
  - admin / guest / presentation 以外のテンプレートで CSS cache-busting が入っていなかった
  - Cloud Run 側で古い `styles.css` を掴んでいた可能性が高い
  - `styles.css?v=...` を全体に適用して解消した

- 解消済み:
  - 管理画面の `投稿一覧` が旧実装っぽく 1列になる問題
  - `当日運用` / `ゲスト管理` の UI 崩れ
  - `登録済みゲスト` の一覧性悪化
  - desktop の `Arc` での CSS 崩れ

## 新たに確認した重要事項

- `/admin` は Basic 認証つきで本番アクセス可能
- `/admin/guests` も Basic 認証つきで本番アクセス可能
- `/admin/guests` 上の `共通 QR コード` 近くに表示される URL は、現在の本番 URL に修正済み
  - 修正後の表示:
    - `https://wedding-photo-contest-228664142250.asia-northeast1.run.app/entry`
  - `APP_URL` のズレは解消済み

## P0: 本番前に最優先で潰す

- [x] Cloud Run 上で `MacBook Air M2 + Arc` の admin UI 崩れを解消した
  - `styles.css` の cache-busting を全体に適用して解消

- [x] `/health` を Cloud Run に反映して、本番 URL で `ok` を確認した
  - 旧 `/healthz` ではなく `/health` を使う運用に変更済み

- [x] Cloud Run 上で主要導線の通し確認をやった
  - `/entry`
  - カテゴリ選択
  - 名前選択
  - 投稿
  - 同一端末での再入場
  - 差し替え
  - 共通 QR
  - 確認済み:
    - `/entry`
    - カテゴリ選択
    - 名前選択
    - join 画面表示
    - remembered guest
    - `/entry/reset`
    - `/entry/qr.svg`
    - 実際の投稿
    - 差し替え

- [x] Cloud Run 上で admin 導線の高優先度確認をやった
  - `/admin`
  - ゲスト追加
  - ゲスト編集
  - ゲスト削除
  - eligible 切替
  - 投稿受付の開閉
  - AI provider 切替
  - 採点実行
  - 手動順位補正 / スコア補正
  - ここまで確認済み:
    - `/admin` への認証つきアクセス
    - `/admin/guests` への認証つきアクセス
    - 画面 HTML の読み取り確認
    - ゲスト追加
    - ゲスト編集
    - ゲスト削除
    - eligible 切替
    - 投稿受付の開閉
    - 採点実行
    - 手動順位補正 / スコア補正
  - 未確認 / 必要なら追加で見る:
    - AI provider 切替の保存挙動

- [x] Cloud Run の `APP_URL` を現在の本番 URL に修正した
  - `/admin/guests` の共通リンク表示は新 URL を向いている
  - `common_entry_url` は修正済み
  - `共通 QR` も同じ helper を使っているため、新 URL 前提になっていると判断できる

- [ ] Cloud Run 上で presentation を実機確認する
  - MacBook Air M2
  - Arc 全画面
  - 16:9 プロジェクター出力
  - クリック進行
  - 戻る操作
  - 紙吹雪タイミング
  - focus -> podium 遷移

- [ ] 本番 URL を最終確定して、共通 QR の印刷物に反映する
  - URL が変わると印刷物を差し替える必要がある

## P1: 当日運用の安全性を上げる

- [x] 本番用ゲスト一覧とテストユーザー登録を完了した
  - 表示名
  - 所属カテゴリ
  - テストユーザー併用前提の状態に整理済み

- [ ] 当日運用手順を 1 回 rehearsal する
  - 投稿受付を開く
  - 数件投稿する
  - 締め切る
  - `mock` で採点する
  - 必要なら手動補正する
  - `/presentation` に切り替える

- [ ] ネットワーク不調時の救済フローを実機で確認する
  - 会場 Wi-Fi
  - 4G/5G
  - 管理側スマホで代理投稿

- [ ] presentation の最後の微調整を 1 回だけやる
  - 余白
  - カード高さ
  - タイトルとの距離
  - podium 全体バランス
  - 演出の開始タイミング
  - 他タスク完了後に最後にまとめてやる

- [x] ゲスト UI の desktop 表示崩れは解消済み
  - `MacBook Air M2 + Arc + Cloud Run` でも問題なし

## P1: AI 準備

- [x] 当日 AI を `mock` のままで行くか決める
  - 本番では外部 AI を入れる方針
  - 第一候補は Gemini
  - 現時点の第一候補モデルは `gemini-2.5-flash`

- [x] 外部 AI の provider / model をひとまず決定した
  - 第一候補:
    - `gemini`
    - `gemini-2.5-flash`
  - 比較候補:
    - `gemini-2.5-flash-lite`
  - Gemini Flash 2.5 は Cloud Run 上で動作確認済み

- [x] 外部 AI 用 secret を準備した
  - `GOOGLE_API_KEY`
  - Secret Manager 登録
  - `roles/secretmanager.secretAccessor` 付与
  - Cloud Run 再デプロイ

- [x] 本番で使う provider で採点が通ることを確認した
  - 1件採点
  - 数件採点
  - 全件採点
  - エラー時に `mock` へ戻せることを確認

- [ ] Gemini free tier の運用上限を見ながら、どこまで実験するか決める
  - 実験用の上限回数を決める
  - 必要なら paid tier へ移行する判断ポイントを決める

- [ ] 必要なら `gemini-2.5-flash-lite` と比較する
  - 速度
  - コメント品質
  - 採点の納得感

## P2: LLM / prompt 整理

- [ ] 採点 prompt とコメント prompt を分離する
  - 採点は写真中心
  - コメントは演出中心

- [ ] relation / episode をどこで持つか決める
  - Guest に持つか
  - Submission に持つか
  - 管理画面から入力するか

- [ ] relation / episode をコメント生成にのみ使う設計にする
  - 採点スコアには混ぜない
  - コメントの楽しさだけに効かせる

- [ ] 上位 3 件だけコメント再生成できる運用を検討する
  - 当日、表示前に少し整える用途

## P2: 参加者向けフィードバック

- [ ] 参加者全員に採点結果とコメントを返す機能を検討する
  - 投稿後すぐ返すか
  - 締切後 / 採点後に返すか
  - guest の join 画面で見せるか
  - 個別 URL で見せるか
  - スコアをそのまま見せるか
  - コメントだけ見せるか

- [ ] 参加者向けフィードバックを返す場合の UX を決める
  - 返すタイミング
  - 再投稿 / 差し替え時の扱い
  - 未採点時の見せ方
  - 本番演出前に順位が読めてしまわない設計にする

- [ ] 参加者向けに点数を返す場合のスコア整合ルールを設計する
  - 1〜3位に選ばれなかった人は、少なくとも `3位の人より高い点数` にならないようにする
  - ランキング対象外の人も、参加者向け表示では `3位の人より高い点数` にならないようにする
  - つまり、参加者へ見せるスコアと、内部採点スコアを分ける可能性がある
  - どの段階で丸めるか
  - コメントは返しても、順位に矛盾しない表示にする

- [ ] 参加者向けフィードバックは二段階フローにする案を検討する
  - まずランキング対象者だけを採点して、1〜3位を確定する
  - `3位の点数` を参加者向け表示スコアの上限として扱う
  - その後、1〜3位以外の人やランキング対象外の人向けに、別プロンプト / 別ロジックでフィードバックを生成する
  - 参加者向けフィードバックは `厳密な審査結果` よりも `納得感のある返却` を重視する
  - 必要なら、内部採点用コメントと参加者向けコメントも分ける

## P3: あとでやる改善

- [ ] `styles.css` の cache-busting を presentation 以外にも広げる
- [ ] 結果の静止画 / PDF バックアップを検討する
- [ ] CSV インポートや二段階審査などの拡張を必要なら後回しで検討する

## 次にやる順番

1. 実機 rehearsal
2. presentation の最後の微調整
3. 必要なら `gemini-2.5-flash-lite` と比較する
