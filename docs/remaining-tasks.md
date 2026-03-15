# Wedding Photo Contest Remaining Tasks

2026-03-15 時点の残タスク整理です。

## 現在地

- Cloud Run service `wedding-photo-contest` への再デプロイは実施済み
- Cloud Run URL:
  - `https://wedding-photo-contest-228664142250.asia-northeast1.run.app`
- `AI_PROVIDER=mock` 前提で動かしている
- `GOOGLE_API_KEY` / `ANTHROPIC_API_KEY` は未設定
- `/admin` は Cloud Run 上でアクセス可能
- `/presentation` は Cloud Run 上でアクセス可能
- `/healthz` は Cloud Run 上で 404
  - 原因判明: Cloud Run の既知制約で、`/healthz` のような一部予約パスは外部 URL で使えない
  - 対応方針: Cloud Run 上の疎通確認は `/health` に統一する
  - コード側でも `/health` を追加し、ローカル互換で `/healthz` も残す

## デプロイ済み環境で追加確認した不具合

- 確認端末 / ブラウザ:
  - `MacBook Air M2`
  - `Arc`
  - Cloud Run のデプロイ済み URL

- ローカル起動 + `MacBook Air M2 + Arc` では再現しない
- `iPhone` では少なくともゲスト UI の大崩れは起きていない
- つまり、`Cloud Run 側だけで古い UI / CSS / asset が出ている` 可能性が高い
  - ただし、現時点では `原因未確定`
  - 仮説:
    - 古い CSS / asset cache
    - Cloud Run に最新コードが完全には反映されていない
    - revision 差分
    - desktop 幅だけで発火する CSS 崩れ

- Cloud Run 上で確認した具体的な問題:
  - 管理画面の `投稿一覧` が、1投稿ずつ横いっぱいに表示され、一覧性が非常に悪い
  - `当日運用` / `ゲスト管理` の UI が壊れていて、単純なハイパーリンクのような見た目になっている
  - `登録済みゲスト` も旧実装の一覧性の悪い UI に見える
  - ゲスト UI も desktop の `Arc` だと色々崩れる
    - ただしゲストは基本スマホ利用想定なので優先度は低め

## P0: 本番前に最優先で潰す

- [ ] Cloud Run 上で `MacBook Air M2 + Arc` の admin UI が崩れる原因を特定する
  - `投稿一覧` が旧実装っぽく 1列で出る原因を確認
  - `当日運用` / `ゲスト管理` のスタイル崩れ原因を確認
  - `登録済みゲスト` の一覧 UI が古く見える原因を確認
  - 仮説: stale cache / 古い CSS / 古い revision / desktop 幅での CSS 崩れ
  - 優先度は高い
    - 当日運用は `MacBook Air M2 + Arc` が本命端末のため

- [ ] `/health` を Cloud Run に反映して、本番 URL で `ok` を確認する
  - 旧 `/healthz` ではなく `/health` を使う
  - 再デプロイ後に `https://.../health` を確認する
  - runbook / deploy 手順の確認先も `/health` に統一する

- [ ] Cloud Run 上で主要導線の通し確認をやる
  - `/entry`
  - カテゴリ選択
  - 名前選択
  - 投稿
  - 同一端末での再入場
  - 差し替え
  - 共通 QR

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

1. `MacBook Air M2 + Arc` で起きる Cloud Run 上の admin UI 崩れ原因特定
2. `/health` を Cloud Run に反映して `ok` を確認
3. Cloud Run 上で通し確認
4. 本番 URL の最終確定と QR fix
5. AI を `mock` のまま行くか / 外部 AI を入れるか決定
6. 実機 rehearsal
7. presentation の最後の微調整
