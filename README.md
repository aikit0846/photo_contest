# Wedding Photo Contest

披露宴の余興として使う、写真投稿 + AI 採点 + 発表画面つきの FastAPI アプリです。

## できること

- ゲストごとの専用 URL / QR コードで写真を 1 枚投稿
- 管理画面から投稿受付の開始 / 締切
- AI 採点プロバイダを `auto / mock / gemini / anthropic / ollama` から切り替え
- 親族などのランキング対象外設定
- 手動で順位固定や点数補正
- プロジェクター投影向けの結果発表画面

## 技術構成

- `FastAPI`
- `Jinja2`
- `SQLAlchemy + SQLite` または `Firestore`
- `local storage` または `Cloud Storage`
- `Pillow`
- `httpx`
- `qrcode`

AI プロバイダは抽象化してあり、現状は次を実装済みです。

- `mock`: API キー不要。ローカルの画像ヒューリスティクスで採点
- `gemini`: Gemini API を利用
- `anthropic`: Claude API を利用
- `ollama`: ローカルの Ollama モデルを利用

`AI_PROVIDER=auto` のときは、`GOOGLE_API_KEY` があれば Gemini を使い、なければ `mock` にフォールバックします。

公開運用は `Cloud Run + Firestore + Cloud Storage` を想定できるようにしてあり、ローカル確認時は `SQLite + local storage` のまま使えます。

## 起動方法

```bash
cp .env.example .env
uv sync
uv run uvicorn app.main:app --reload
```

ブラウザで [http://127.0.0.1:8000](http://127.0.0.1:8000) を開いてください。

管理画面は [http://127.0.0.1:8000/admin](http://127.0.0.1:8000/admin) です。

`ADMIN_PASSWORD` を設定した場合、ユーザー名 `admin` の Basic 認証が有効になります。

投稿画面では、対応ブラウザならアップロード前に画像を軽量化してから送信します。非対応ブラウザでは通常のフォーム送信にフォールバックします。

Cloud Run には `requirements.txt` も置いてあり、buildpacks 側で安定した依存解決経路を使えるようにしています。

## デモゲスト投入

```bash
uv run python scripts/seed_demo.py
```

## 環境変数

- `APP_URL`: QR コードに埋め込む URL のベース
- `ADMIN_PASSWORD`: 管理画面の Basic 認証パスワード
- `DATA_BACKEND`: `sqlite` or `firestore`
- `STORAGE_BACKEND`: `local` or `gcs`
- `FIRESTORE_PROJECT`
- `FIRESTORE_DATABASE`
- `GCS_BUCKET`
- `AI_PROVIDER`: `auto`, `mock`, `gemini`, `anthropic`, `ollama`
- `GOOGLE_API_KEY`
- `GOOGLE_MODEL`
- `ANTHROPIC_API_KEY`
- `ANTHROPIC_MODEL`
- `OLLAMA_BASE_URL`
- `OLLAMA_MODEL`
- `TARGET_IMAGE_MAX_EDGE`
- `TARGET_IMAGE_QUALITY`

## 今後の拡張候補

- 受付名簿 CSV インポート
- 上位候補のみ再採点する二段階審査
- 結果の静的 PDF / PNG 出力
- 投稿後の自動採点キュー

## 本番公開メモ

- GCP 初期セットアップは [docs/gcp-setup.md](/Users/taikisuzuki/wedding/photo_contest/docs/gcp-setup.md)
- Cloud Run の source deploy 前提で `Procfile` を追加済みです
- Cloud Run 用の詳細手順は [docs/cloud-run.md](/Users/taikisuzuki/wedding/photo_contest/docs/cloud-run.md)
- 本番前の確認事項と救済フローは [docs/runbook.md](/Users/taikisuzuki/wedding/photo_contest/docs/runbook.md)
- 今日はここで止めるときの扱いは [docs/cloud-run.md](/Users/taikisuzuki/wedding/photo_contest/docs/cloud-run.md) の「作業を止めるとき」を参照
