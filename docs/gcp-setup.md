# GCP Setup Before Cloud Run

`docs/cloud-run.md` に入る前に、一度だけやっておく GCP 初期セットアップです。

このアプリでは、次の前提を置きます。

- 実行環境: `Cloud Run`
- 画像保存: `Cloud Storage`
- メタデータ保存: `Firestore`
- 秘密情報: `Secret Manager`
- デプロイ方法: `Cloud Shell` から `gcloud run deploy --source .`

## 0. 先に決めるもの

- `PROJECT_NAME`
- `PROJECT_ID`
- `REGION`
  - 基本は `asia-northeast1`
- `BUCKET_NAME`
  - グローバル一意である必要があります

おすすめ例:

- `PROJECT_NAME`: `Wedding Photo Contest`
- `PROJECT_ID`: `wedding-photo-contest-2026`
- `REGION`: `asia-northeast1`
- `BUCKET_NAME`: `wedding-photo-contest-2026-assets`

## 1. Google Cloud アカウントと Billing

最初に必要なのはこれです。

- Google アカウントで Google Cloud Console にログイン
- Billing account を作成
- 新しい project を作成
- その project に Billing を紐付ける

ポイント:

- project ID はあとから変えられません
- Billing が有効でないと Cloud Run など多くの機能は使えません
- コストが気になるなら、最初に budget alert を作るのがおすすめです

## 2. 予算アラートを作る

結婚式用途なら、最初に `数ドル` の budget alert を入れておくと安心です。

おすすめ:

- 月額 budget: `$5` または `$10`
- alert threshold: `50%`, `90%`, `100%`

budget は上限ではなく通知です。自動停止ではありません。

## 3. 新規 project を作る

新しい project を使うのがおすすめです。既存 project より location や IAM の事故を避けやすいです。

Cloud Shell を使う前でも Console で作成できます。

Cloud Shell で作るなら:

```bash
gcloud projects create PROJECT_ID --name="PROJECT_NAME"
gcloud config set project PROJECT_ID
```

もし organization 配下で project 作成がブロックされるなら、個人アカウント側で作るか、管理者に権限をもらう必要があります。

## 4. Cloud Shell を開く

Google Cloud Console 右上の `>_` アイコンから Cloud Shell を開きます。

初回は authorize が必要です。Cloud Shell の認可はその session の間だけ有効です。ブラウザを閉じたり VM を再起動すると、次回 session で再度 authorize が必要になることがあります。

Cloud Shell を開いたら:

```bash
gcloud config set project PROJECT_ID
gcloud config set run/region asia-northeast1
```

## 5. API を有効化

```bash
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com \
  firestore.googleapis.com \
  storage.googleapis.com
```

補足:

- `gcloud run deploy --source .` は Cloud Build と buildpacks を使います
- Artifact Registry の `cloud-run-source-deploy` repo は、初回 deploy 時に自動作成されます

## 6. project number を確認

あとで Cloud Build service account に権限をつけるので、project number を先に見ておくと楽です。

```bash
gcloud projects describe PROJECT_ID --format='value(projectNumber)'
```

## 7. Firestore を作る

このアプリでは Firestore Native を使う前提です。

```bash
gcloud firestore databases create \
  --database='(default)' \
  --location=asia-northeast1 \
  --edition=standard \
  --type=firestore-native
```

注意:

- Firestore の location はあとから変えられません
- もし別サービスの都合で default resource location がすでに確定している project だと、思った region を選べないことがあります
- 迷うなら fresh な project を使うのが安全です

## 8. Cloud Storage bucket を作る

```bash
gcloud storage buckets create gs://BUCKET_NAME \
  --project=PROJECT_ID \
  --location=asia-northeast1 \
  --default-storage-class=STANDARD \
  --uniform-bucket-level-access
```

ポイント:

- bucket 名はグローバル一意です
- `uniform-bucket-level-access` は有効化しておくのが簡単です

## 9. Cloud Run 実行用 service account を作る

```bash
gcloud iam service-accounts create photo-contest-run \
  --display-name="photo contest run"
```

作成後、次のような email になります。

```text
photo-contest-run@PROJECT_ID.iam.gserviceaccount.com
```

## 10. Cloud Run 実行用 service account に権限を付ける

Firestore と Storage を触れる必要があります。

```bash
gcloud projects add-iam-policy-binding PROJECT_ID \
  --member="serviceAccount:photo-contest-run@PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/datastore.user"

gcloud storage buckets add-iam-policy-binding gs://BUCKET_NAME \
  --member="serviceAccount:photo-contest-run@PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/storage.objectAdmin"
```

## 11. Cloud Build service account に builder 権限を付ける

source deploy では Cloud Build が build を担当します。Cloud Run quickstart でも、Cloud Build service account に `roles/run.builder` を付与する手順があります。

`PROJECT_NUMBER` を確認したうえで:

```bash
gcloud projects add-iam-policy-binding PROJECT_ID \
  --member="serviceAccount:PROJECT_NUMBER-compute@developer.gserviceaccount.com" \
  --role="roles/run.builder"
```

権限の反映に数分かかることがあります。

## 12. Secret Manager を使う準備

少なくとも `ADMIN_PASSWORD` は secret にしたほうがいいです。

必要に応じて:

- `ADMIN_PASSWORD`
- `GOOGLE_API_KEY`
- `ANTHROPIC_API_KEY`

作成例:

```bash
printf 'YOUR_ADMIN_PASSWORD' | gcloud secrets create ADMIN_PASSWORD --data-file=-
printf 'YOUR_GOOGLE_API_KEY' | gcloud secrets create GOOGLE_API_KEY --data-file=-
printf 'YOUR_ANTHROPIC_API_KEY' | gcloud secrets create ANTHROPIC_API_KEY --data-file=-
```

Cloud Run 実行用 service account に secret access を付けます。

```bash
gcloud secrets add-iam-policy-binding ADMIN_PASSWORD \
  --member="serviceAccount:photo-contest-run@PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"

gcloud secrets add-iam-policy-binding GOOGLE_API_KEY \
  --member="serviceAccount:photo-contest-run@PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"

gcloud secrets add-iam-policy-binding ANTHROPIC_API_KEY \
  --member="serviceAccount:photo-contest-run@PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
```

使わない secret は作成・付与しなくて大丈夫です。

## 13. ここまで終わったら

ここまでで、ようやく `docs/cloud-run.md` の deploy 手順に入れます。

次に必要なのは:

- GitHub からコードを Cloud Shell に clone
- `gcloud run deploy --source .`
- 発行された `run.app` URL を `APP_URL` に入れて再 deploy

## 14. もし詰まりやすい点

- project 作成で権限不足
  - `roles/resourcemanager.projectCreator` がない可能性があります
- API 有効化で権限不足
  - `roles/serviceusage.serviceUsageAdmin` がない可能性があります
- Billing を project に紐付けられない
  - Billing account 側の権限が足りない可能性があります
- public access を許可できない
  - 組織ポリシーで unauthenticated invocation が制限されている可能性があります

個人アカウントで新規 project を切るなら、たいていはかなり素直に進みます。
