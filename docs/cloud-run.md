# Cloud Run Deployment

Docker を使わず、`Cloud Shell` から `gcloud run deploy --source .` する前提のメモです。

## 先に決めておくもの

- `YOUR_PROJECT_ID`
- `YOUR_REGION` : まずは `asia-northeast1`
- `YOUR_BUCKET_NAME`
- `ADMIN_PASSWORD`
- 使うなら `GOOGLE_API_KEY` / `ANTHROPIC_API_KEY`

## このコードで追加済みの対応

- `DATA_BACKEND=firestore` で Firestore を使えるようにした
- `STORAGE_BACKEND=gcs` で Cloud Storage を使えるようにした
- `Procfile` を追加したので Cloud Run source deploy で起動方法を固定しやすい
- `requirements.txt` を追加したので、Cloud Run buildpacks では preview の `pyproject.toml` 直読みを避けやすい
- `/healthz` を追加した
- 投稿画面で対応ブラウザなら画像を軽量化してから送る

## GCP 側でやること

### 1. プロジェクトとリージョン

```bash
gcloud config set project YOUR_PROJECT_ID
gcloud config set run/region asia-northeast1
```

### 2. API 有効化

```bash
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com \
  firestore.googleapis.com \
  storage.googleapis.com
```

### 3. Firestore 作成

```bash
gcloud firestore databases create \
  --database='(default)' \
  --location=asia-northeast1 \
  --edition=standard \
  --type=firestore-native
```

### 4. Cloud Storage bucket 作成

```bash
gcloud storage buckets create gs://YOUR_BUCKET_NAME \
  --location=asia-northeast1 \
  --uniform-bucket-level-access
```

### 5. Cloud Run 用 service account

```bash
gcloud iam service-accounts create photo-contest-run \
  --display-name="photo contest run"
```

### 6. 権限付与

```bash
gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
  --member="serviceAccount:photo-contest-run@YOUR_PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/datastore.user"

gcloud storage buckets add-iam-policy-binding gs://YOUR_BUCKET_NAME \
  --member="serviceAccount:photo-contest-run@YOUR_PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/storage.objectAdmin"
```

### 7. Secret Manager

```bash
printf 'YOUR_ADMIN_PASSWORD' | gcloud secrets create ADMIN_PASSWORD --data-file=-
printf 'YOUR_GOOGLE_API_KEY' | gcloud secrets create GOOGLE_API_KEY --data-file=-
printf 'YOUR_ANTHROPIC_API_KEY' | gcloud secrets create ANTHROPIC_API_KEY --data-file=-
```

```bash
gcloud secrets add-iam-policy-binding ADMIN_PASSWORD \
  --member="serviceAccount:photo-contest-run@YOUR_PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"

gcloud secrets add-iam-policy-binding GOOGLE_API_KEY \
  --member="serviceAccount:photo-contest-run@YOUR_PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"

gcloud secrets add-iam-policy-binding ANTHROPIC_API_KEY \
  --member="serviceAccount:photo-contest-run@YOUR_PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
```

API キーを使わないなら、その secret は省略して大丈夫です。

## Cloud Shell でのデプロイ

### 1. コード取得

Cloud Shell では、private repository を SSH で clone しようとすると GitHub 公開鍵の設定が必要になります。
最短で進めたい場合は、次のどちらかです。

- 一時的に repository を `public` にして、`HTTPS` で clone する
- private のまま `HTTPS + GitHub token` で clone する

今回の用途では、一時的に public にして deploy 後に private に戻すのがいちばん簡単です。

```bash
git clone https://github.com/aikit0846/photo_contest.git
cd photo_contest
```

補足:

- `git clone git@github.com:...` は public repository でも SSH 認証が必要です
- public にしただけでは `git@github.com:...` は通りません
- public 化した場合でも、Cloud Shell では `https://github.com/...` を使うのが安全です

### 2. 初回 deploy

`APP_URL` はまだ不明なので、最初はダミーでも構いません。

```bash
gcloud run deploy wedding-photo-contest \
  --source . \
  --region asia-northeast1 \
  --allow-unauthenticated \
  --service-account photo-contest-run@YOUR_PROJECT_ID.iam.gserviceaccount.com \
  --cpu 1 \
  --memory 1Gi \
  --concurrency 8 \
  --max-instances 3 \
  --min-instances 0 \
  --timeout 60 \
  --set-env-vars APP_URL=https://example.invalid,DATA_BACKEND=firestore,STORAGE_BACKEND=gcs,FIRESTORE_PROJECT=YOUR_PROJECT_ID,FIRESTORE_DATABASE='(default)',GCS_BUCKET=YOUR_BUCKET_NAME,AI_PROVIDER=auto \
  --update-secrets ADMIN_PASSWORD=ADMIN_PASSWORD:latest,GOOGLE_API_KEY=GOOGLE_API_KEY:latest,ANTHROPIC_API_KEY=ANTHROPIC_API_KEY:latest
```

### 3. URL 取得

```bash
gcloud run services describe wedding-photo-contest \
  --region asia-northeast1 \
  --format='value(status.url)'
```

### 4. APP_URL を本番URLで更新して再 deploy

```bash
gcloud run deploy wedding-photo-contest \
  --source . \
  --region asia-northeast1 \
  --allow-unauthenticated \
  --service-account photo-contest-run@YOUR_PROJECT_ID.iam.gserviceaccount.com \
  --cpu 1 \
  --memory 1Gi \
  --concurrency 8 \
  --max-instances 3 \
  --min-instances 0 \
  --timeout 60 \
  --set-env-vars APP_URL=https://YOUR_RUN_APP_URL,DATA_BACKEND=firestore,STORAGE_BACKEND=gcs,FIRESTORE_PROJECT=YOUR_PROJECT_ID,FIRESTORE_DATABASE='(default)',GCS_BUCKET=YOUR_BUCKET_NAME,AI_PROVIDER=auto \
  --update-secrets ADMIN_PASSWORD=ADMIN_PASSWORD:latest,GOOGLE_API_KEY=GOOGLE_API_KEY:latest,ANTHROPIC_API_KEY=ANTHROPIC_API_KEY:latest
```

## デプロイ後の確認

- `/healthz` が `ok` を返す
- `/admin` に Basic 認証で入れる
- ゲスト追加ができる
- ゲスト専用 URL が `run.app` ドメインになっている
- 画像投稿できる
- `AI_PROVIDER=mock` でまず採点フローを通せる
- その後、必要なら `gemini` などに切り替える

## ローカルと本番の切り替え

### ローカル

```env
DATA_BACKEND=sqlite
STORAGE_BACKEND=local
```

### Cloud Run

```env
DATA_BACKEND=firestore
STORAGE_BACKEND=gcs
FIRESTORE_PROJECT=YOUR_PROJECT_ID
FIRESTORE_DATABASE=(default)
GCS_BUCKET=YOUR_BUCKET_NAME
```

## 作業を止めるとき

### 結論

- 今の設定が `min-instances=0` かつ request-based billing なら、サービスを置いたままでもアイドル時の Cloud Run compute 課金はありません
- ただし、`Firestore`、`Cloud Storage`、`Artifact Registry` の保存量や、外部からのアクセスがあればその分は課金対象になりえます

短く止めるだけなら:

- そのまま放置で問題ないことが多いです
- ただし、完全に安心したいなら Cloud Run service を削除するのがいちばん分かりやすいです

### いったん service だけ止めたい場合

データは残したまま、Cloud Run だけ消す:

```bash
gcloud run services delete wedding-photo-contest --region asia-northeast1
```

残るもの:

- Firestore のデータ
- Cloud Storage の画像
- Artifact Registry の build image
- Secret Manager の secret

この状態なら、あとで同じ `gcloud run deploy --source .` で再作成できます。

### さらにきれいにしたい場合

Cloud Run service に加えて、不要なら次も掃除できます。

- Artifact Registry の image を削除
- Cloud Storage bucket の画像を削除
- Firestore のテストデータを削除

ただし、再開時に投稿データを残したいなら Firestore / Cloud Storage は消さない方がよいです。

### 結婚式本番前におすすめ

- 開発中は service を消してもよい
- 本番が近づいたら deploy し直して URL を固定する
- URL が変わると QR コードを刷り直す必要があるので、最終 URL 確定後は service を消さない方が安全です
