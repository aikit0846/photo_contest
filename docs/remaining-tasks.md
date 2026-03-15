# Wedding Photo Contest Remaining Tasks

2026-03-15 時点の残タスク整理です。

## 現在地

- Cloud Run service `wedding-photo-contest` への再デプロイは実施済み
- Cloud Run URL:
  - `https://wedding-photo-contest-228664142250.asia-northeast1.run.app`
- `AI_PROVIDER=mock` 前提で動かしている
- `GOOGLE_API_KEY` / `ANTHROPIC_API_KEY` は未設定
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
  - desktop の `Arc` での CSS 崩れの大部分

## P0: 本番前に最優先で潰す

- [x] Cloud Run 上で `MacBook Air M2 + Arc` の admin UI 崩れを解消した
  - `styles.css` の cache-busting を全体に適用して解消

- [x] `/health` を Cloud Run に反映して、本番 URL で `ok` を確認した
  - 旧 `/healthz` ではなく `/health` を使う運用に変更済み

- [ ] Cloud Run 上で主要導線の通し確認をやる
  - `/entry`
  - カテゴリ選択
  - 名前選択
  - 投稿
  - 同一端末での再入場
  - 差し替え
  - 共通 QR
  - ここまで確認済み:
    - `/entry`
    - カテゴリ選択
    - 名前選択
    - join 画面表示
    - remembered guest
    - `/entry/reset`
    - `/entry/qr.svg`
  - 未確認:
    - 実際の投稿
    - 差し替え
  - 未確認理由:
    - 本番データを更新するため、実施判断を分けたい

- [ ] Cloud Run 上で admin 導線を通し確認する
  - `/admin`
  - ゲスト追加
  - ゲスト編集
  - ゲスト削除
  - eligible 切替
  - 投稿受付の開閉
  - AI provider 切替
  - 採点実行
  - 手動順位補正 / スコア補正
  - 現状のブロッカー:
    - 本番 `/admin` は Basic 認証が必要
    - 認証情報なしでは 401

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

- [ ] 本番用ゲスト一覧を最終確定する
  - 表示名
  - 所属カテゴリ
  - eligible
  - 対象外設定の必要有無

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

- [ ] ゲスト UI の desktop 表示崩れを確認する
  - 再現条件: `MacBook Air M2 + Arc + Cloud Run`
  - `iPhone` では優先度が低いので後回しでよい
  - ただし desktop で壊れている理由は一度把握しておく

## P1: AI 準備

- [ ] 当日 AI を `mock` のままで行くか決める
  - 安定性優先なら `mock`
  - 演出優先なら `gemini` or `anthropic`

- [ ] 外部 AI を使うなら provider を 1 つに絞る
  - 第一候補
  - 予備候補
  - 本番当日に迷わない状態にする

- [ ] 外部 AI を使うなら secret を準備する
  - `GOOGLE_API_KEY` または `ANTHROPIC_API_KEY`
  - Secret Manager 登録
  - `roles/secretmanager.secretAccessor` 付与
  - Cloud Run 再デプロイ

- [ ] 本番で使う provider で採点が通ることを確認する
  - 1件採点
  - 数件採点
  - 全件採点
  - エラー時に `mock` へ戻せることを確認

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

## P3: あとでやる改善

- [ ] `styles.css` の cache-busting を presentation 以外にも広げる
- [ ] 結果の静止画 / PDF バックアップを検討する
- [ ] CSV インポートや二段階審査などの拡張を必要なら後回しで検討する

## 次にやる順番

1. Cloud Run 上の guest 導線のうち、実投稿 / 差し替え確認をやるか決めて実施
2. admin 導線の本番確認をやる
3. 本番 URL の最終確定と QR fix
4. AI を `mock` のまま行くか / 外部 AI を入れるか決定
5. 実機 rehearsal
6. presentation の最後の微調整
