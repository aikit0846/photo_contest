# Cloud Run Deployment

Docker を使わず、`Cloud Shell` から `gcloud run deploy --source .` する前提のメモです。

## 先に決めておくもの

- `PROJECT_ID=wedding-photo-contest-20260419`
- `REGION=asia-northeast1`
- `BUCKET_NAME=wedding-photo-contest-20260419-assets`
- `SERVICE_NAME=wedding-photo-contest`
- `ADMIN_PASSWORD`
- 使うなら `GOOGLE_API_KEY`
- 採点ジョブをブラウザから切り離したいなら:
  - `CLOUD_TASKS_QUEUE=judging-jobs`
  - `CLOUD_TASKS_TOKEN`

## このプロジェクトで使う値

この repository では、少なくとも次の値は固定前提で書いてよいです。

```bash
export PROJECT_ID=wedding-photo-contest-20260419
export REGION=asia-northeast1
export BUCKET_NAME=wedding-photo-contest-20260419-assets
export SERVICE_NAME=wedding-photo-contest
```

`APP_URL` だけは、Cloud Run service の実 URL を使います。

- すでに service が存在するなら、先に現在の URL を取得してそのまま使えばよい
- 同じ `SERVICE_NAME` に再 deploy する限り、通常は URL は変わらない
- つまり再デプロイ時は、まず今の URL を見ればよい

```bash
gcloud run services describe "$SERVICE_NAME" \
  --region "$REGION" \
  --format='value(status.url)'
```

出てきた URL を `APP_URL` に入れます。例:

```bash
export APP_URL="$(gcloud run services describe "$SERVICE_NAME" --region "$REGION" --format='value(status.url)')"
echo "$APP_URL"
```

## このコードで追加済みの対応

- `DATA_BACKEND=firestore` で Firestore を使えるようにした
- `STORAGE_BACKEND=gcs` で Cloud Storage を使えるようにした
- `Procfile` を追加したので Cloud Run source deploy で起動方法を固定しやすい
- `requirements.txt` を追加したので、Cloud Run buildpacks では preview の `pyproject.toml` 直読みを避けやすい
- `/health` を追加した
- ローカル互換で `/healthz` も残している
- 投稿画面で対応ブラウザなら画像を軽量化してから送る

## まず結論

### 初回セットアップでだけ必要

- この md の `GCP 側でやること` を最初から最後までやる
- Cloud Run service account、Firestore、Cloud Storage、Secret Manager を作る
- 初回 deploy 後に Cloud Run の URL を取得し、`APP_URL` を本番 URL にして再 deploy する

### 2回目以降の再デプロイで毎回必要

- 最新コードを Cloud Shell 側に持ってくる
- `gcloud config set project ...`
- `gcloud config set run/region ...`
- `gcloud run deploy wedding-photo-contest --source . ...`
- deploy 後に `/health`、`/admin`、`/presentation` を確認する

### 変更があったときだけ必要

- `APP_URL` が変わるとき: `--set-env-vars APP_URL=...` を更新する
- Secret の値が変わるとき: Secret Manager を更新する
- env var を追加・変更したとき: `gcloud run deploy` の `--set-env-vars` を更新する
- service を一度削除しているとき: 通常の `gcloud run deploy --source .` で再作成する

## 再デプロイだけしたい場合

GCP 側の初回セットアップが終わっていて、Cloud Run service もすでに存在する前提なら、通常は次の手順だけで十分です。

### 1. Cloud Shell で最新コードを取得

```bash
cd photo_contest
git pull
```

Cloud Shell にまだ repository がない場合だけ、後述の `Cloud Shell でのデプロイ -> コード取得` をやってください。

### 2. project / region を確認

```bash
gcloud config set project "$PROJECT_ID"
gcloud config set run/region "$REGION"
```

### 3. いまの APP_URL を取得

同じ Cloud Run service に再 deploy するなら、今の service URL をそのまま `APP_URL` に使えば大丈夫です。

```bash
export APP_URL="$(gcloud run services describe "$SERVICE_NAME" --region "$REGION" --format='value(status.url)')"
echo "$APP_URL"
```

もしまだ service が存在しない場合だけ、後ろの `初回 deploy` から始めてください。

### 4. 再デプロイ

#### いまのおすすめ: API キー未設定のまま `mock` で再デプロイ

モデル未確定で、`GOOGLE_API_KEY` をまだ作っていないなら、この形がいちばん安全です。

```bash
gcloud run deploy "$SERVICE_NAME" \
  --source . \
  --region "$REGION" \
  --allow-unauthenticated \
  --service-account "photo-contest-run@$PROJECT_ID.iam.gserviceaccount.com" \
  --cpu 1 \
  --memory 1Gi \
  --concurrency 8 \
  --max-instances 3 \
  --min-instances 0 \
  --timeout 60 \
  --set-env-vars APP_URL="$APP_URL",DATA_BACKEND=firestore,STORAGE_BACKEND=gcs,FIRESTORE_PROJECT="$PROJECT_ID",FIRESTORE_DATABASE='(default)',GCS_BUCKET="$BUCKET_NAME",AI_PROVIDER=mock \
  --remove-secrets GOOGLE_API_KEY \
  --update-secrets ADMIN_PASSWORD=ADMIN_PASSWORD:latest
```

#### Google API キーを使う場合の再デプロイ

`Gemini` を使う段階になったら、次のように secret を追加します。

`APP_URL` が変わらないなら、基本的にはこのコマンドで再デプロイできます。

```bash
gcloud run deploy "$SERVICE_NAME" \
  --source . \
  --region "$REGION" \
  --allow-unauthenticated \
  --service-account "photo-contest-run@$PROJECT_ID.iam.gserviceaccount.com" \
  --cpu 1 \
  --memory 1Gi \
  --concurrency 8 \
  --max-instances 3 \
  --min-instances 0 \
  --timeout 60 \
  --set-env-vars APP_URL="$APP_URL",DATA_BACKEND=firestore,STORAGE_BACKEND=gcs,FIRESTORE_PROJECT="$PROJECT_ID",FIRESTORE_DATABASE='(default)',GCS_BUCKET="$BUCKET_NAME",AI_PROVIDER=auto \
  --update-secrets ADMIN_PASSWORD=ADMIN_PASSWORD:latest,GOOGLE_API_KEY=GOOGLE_API_KEY:latest
```

#### Cloud Tasks で採点ジョブを回す場合の再デプロイ

iPhone で開始だけ押して離れたいなら、Cloud Tasks を有効にした状態で再 deploy します。

```bash
export CLOUD_TASKS_QUEUE=judging-jobs

gcloud run deploy "$SERVICE_NAME" \
  --source . \
  --region "$REGION" \
  --allow-unauthenticated \
  --service-account "photo-contest-run@$PROJECT_ID.iam.gserviceaccount.com" \
  --cpu 1 \
  --memory 1Gi \
  --concurrency 8 \
  --max-instances 3 \
  --min-instances 0 \
  --timeout 60 \
  --set-env-vars APP_URL="$APP_URL",DATA_BACKEND=firestore,STORAGE_BACKEND=gcs,FIRESTORE_PROJECT="$PROJECT_ID",FIRESTORE_DATABASE='(default)',GCS_BUCKET="$BUCKET_NAME",AI_PROVIDER=auto,CLOUD_TASKS_PROJECT="$PROJECT_ID",CLOUD_TASKS_LOCATION="$REGION",CLOUD_TASKS_QUEUE="$CLOUD_TASKS_QUEUE" \
  --update-secrets ADMIN_PASSWORD=ADMIN_PASSWORD:latest,GOOGLE_API_KEY=GOOGLE_API_KEY:latest,CLOUD_TASKS_TOKEN=CLOUD_TASKS_TOKEN:latest
```

この構成では:

- 採点開始は iPhone から押せる
- その後の task 実行は Cloud Tasks が進める
- MacBook Air では `/admin` を開いて進捗確認と結果確認だけすればよい

### 5. デプロイ後の確認

- `GET /health` が `ok`
- `/admin` に入れる
- `/presentation` が崩れていない
- 必要なら `AI_PROVIDER=mock` で採点を通す
- Cloud Tasks を有効にした場合:
  - `/admin` で採点開始後、別端末から開いても進捗が見える
  - 開始端末を閉じても採点が継続する

## GCP 側でやること

以下は基本的に `初回セットアップ時だけ` 必要です。

### 1. プロジェクトとリージョン

```bash
gcloud config set project "$PROJECT_ID"
gcloud config set run/region "$REGION"
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
  --location="$REGION" \
  --edition=standard \
  --type=firestore-native
```

### 4. Cloud Storage bucket 作成

```bash
gcloud storage buckets create "gs://$BUCKET_NAME" \
  --location="$REGION" \
  --uniform-bucket-level-access
```

### 5. Cloud Run 用 service account

```bash
gcloud iam service-accounts create photo-contest-run \
  --display-name="photo contest run"
```

### 6. 権限付与

```bash
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:photo-contest-run@$PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/datastore.user"

gcloud storage buckets add-iam-policy-binding "gs://$BUCKET_NAME" \
  --member="serviceAccount:photo-contest-run@$PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/storage.objectAdmin"
```

### 7. Secret Manager

```bash
printf 'YOUR_ADMIN_PASSWORD' | gcloud secrets create ADMIN_PASSWORD --data-file=-
printf 'YOUR_GOOGLE_API_KEY' | gcloud secrets create GOOGLE_API_KEY --data-file=-
```

```bash
gcloud secrets add-iam-policy-binding ADMIN_PASSWORD \
  --member="serviceAccount:photo-contest-run@$PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"

gcloud secrets add-iam-policy-binding GOOGLE_API_KEY \
  --member="serviceAccount:photo-contest-run@$PROJECT_ID.iam.gserviceaccount.com" \
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

まずは API キーなしで `mock` だけ動けばよいなら、この形で十分です。

```bash
gcloud run deploy "$SERVICE_NAME" \
  --source . \
  --region "$REGION" \
  --allow-unauthenticated \
  --service-account "photo-contest-run@$PROJECT_ID.iam.gserviceaccount.com" \
  --cpu 1 \
  --memory 1Gi \
  --concurrency 8 \
  --max-instances 3 \
  --min-instances 0 \
  --timeout 60 \
  --set-env-vars APP_URL=https://example.invalid,DATA_BACKEND=firestore,STORAGE_BACKEND=gcs,FIRESTORE_PROJECT="$PROJECT_ID",FIRESTORE_DATABASE='(default)',GCS_BUCKET="$BUCKET_NAME",AI_PROVIDER=mock \
  --remove-secrets GOOGLE_API_KEY \
  --update-secrets ADMIN_PASSWORD=ADMIN_PASSWORD:latest
```

あとから `Gemini` を使うときだけ、secret を作成して `--update-secrets GOOGLE_API_KEY=...` を追加してください。

### 3. URL 取得

```bash
gcloud run services describe "$SERVICE_NAME" \
  --region "$REGION" \
  --format='value(status.url)'
```

### 4. APP_URL を本番URLで更新して再 deploy

まず URL を取得:

```bash
export APP_URL="$(gcloud run services describe "$SERVICE_NAME" --region "$REGION" --format='value(status.url)')"
echo "$APP_URL"
```

```bash
gcloud run deploy "$SERVICE_NAME" \
  --source . \
  --region "$REGION" \
  --allow-unauthenticated \
  --service-account "photo-contest-run@$PROJECT_ID.iam.gserviceaccount.com" \
  --cpu 1 \
  --memory 1Gi \
  --concurrency 8 \
  --max-instances 3 \
  --min-instances 0 \
  --timeout 60 \
  --set-env-vars APP_URL="$APP_URL",DATA_BACKEND=firestore,STORAGE_BACKEND=gcs,FIRESTORE_PROJECT="$PROJECT_ID",FIRESTORE_DATABASE='(default)',GCS_BUCKET="$BUCKET_NAME",AI_PROVIDER=mock \
  --remove-secrets GOOGLE_API_KEY \
  --update-secrets ADMIN_PASSWORD=ADMIN_PASSWORD:latest
```

API キーを使う段階になったら、ここでも `AI_PROVIDER=auto` などに変えて `GOOGLE_API_KEY` を足します。

## デプロイ後の確認

- `/health` が `ok` を返す
- `/admin` に Basic 認証で入れる
- ゲスト追加ができる
- ゲスト専用 URL が `run.app` ドメインになっている
- 画像投稿できる
- `AI_PROVIDER=mock` でまず採点フローを通せる
- その後、必要なら `gemini` などに切り替える

## よくあるハマりどころ

### Cloud Run では `/healthz` を使わず `/health` を使う

Cloud Run には、外部公開 URL では使えない予約 URL パスがあります。
公式の known issues に、`/healthz` を含む「末尾が `z` の一部パス」は予約扱いになることがあると書かれています。

この project では次の運用にします。

- Cloud Run 上の疎通確認は `/health` を使う
- `/healthz` はローカル互換のためコード上は残してよい
- 本番 run.app URL の確認コマンドや手順書は `/health` に統一する

### Secret Manager の権限不足で deploy が失敗する

次のようなエラーが出ることがあります。

- `Permission denied on secret ... GOOGLE_API_KEY`
- `Permission denied on secret ... GOOGLE_API_KEY`

これは Cloud Run の service account に、その secret の `Secret Accessor` 権限が付いていないのが原因です。

この project では、まず次を実行します。

```bash
gcloud secrets add-iam-policy-binding GOOGLE_API_KEY \
  --member="serviceAccount:photo-contest-run@$PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
```

その後、もう一度 `gcloud run deploy ...` を実行してください。

もし今回は API キーを使わず、`mock` だけでよいなら、deploy コマンドの `--update-secrets` から `GOOGLE_API_KEY` を外すだけでなく、`--remove-secrets GOOGLE_API_KEY` も付けて既存の参照を消してください。

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
FIRESTORE_PROJECT=wedding-photo-contest-20260419
FIRESTORE_DATABASE=(default)
GCS_BUCKET=wedding-photo-contest-20260419-assets
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
gcloud run services delete "$SERVICE_NAME" --region "$REGION"
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
