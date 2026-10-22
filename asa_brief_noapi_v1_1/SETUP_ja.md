# iPhoneホーム画面から使うまでの手順（追加API料金なし）

作業は最初の公開設定だけWindows PCのブラウザで行い、日常の閲覧はiPhoneで行います。PC常時起動は不要です。GitHub Freeの公開リポジトリ、標準のubuntu-latest、GitHub Pagesを使います。独自ドメイン・有料ランナー・有料APIは使いません。サービスの規約・利用枠が変わる可能性までは保証しません。

## 1. 新しい版を展開する

`asa_brief_noapi_v1_1.zip` をPCに保存し、右クリック →「すべて展開」。
`index.html` と `assets`、`config`、`data`、`tools`、`tests` が見えるフォルダまで開いてください。
古いZIPや単体プレビューHTMLは正式版の公開に使わないでください。

## 2. 専用のPublicリポジトリを作る

GitHubにログイン → 右上の「+」→「New repository」。
Repository nameは `asa-brief`、Visibilityは `Public`。
「Add a README file」をオンにして「Create repository」。既に同名リポジトリがある場合は、中身を確認せず上書きしないでください。

**Publicはインターネット上で公開される設定です。既存の研究・投資用リポジトリの公開範囲は変えません。**
この専用リポジトリに個人の情報、キー、資産データを入れないでください。

## 3. アプリの中身をアップロードする

新しいリポジトリの「Code」→「Add file」→「Upload files」。
展開したフォルダの中身を、フォルダ構造ごとドラッグ＆ドロップします。
親フォルダやZIPをそのまま入れないでください。

最後は「Commit changes」。新しい自分専用の空のリポジトリではmainに保存します。
ブランチ作成を選んだ場合は、変更をmainへマージしてから次へ進みます。

リポジトリの最上段に次のように並べば正しい形です。

```text
.github/workflows/daily-news.yml
assets/
config/
data/
tests/
tools/
index.html
manifest.webmanifest
sw.js
README.md
SETUP_ja.md
```

特に `.github/workflows/daily-news.yml` が存在することをクリックして確認します。
ブラウザのアップロードで `.github` が入らなかった場合:
「Add file」→「Create new file」→ファイル名を `.github/workflows/daily-news.yml` にする→同梱の `daily-news.yml`（または別添 `daily-news-noapi.yml.txt`）の内容を全部貼り付けて保存します。リポジトリでの拡張子は `.yml` で終わり、`.txt` は付けません。

## 4. GitHub Pagesを設定する

リポジトリの「Settings」→ 左の「Pages」。
「Build and deployment」の「Source」を **GitHub Actions** に設定します。
「Deploy from a branch」は選びません。既存ワークフローがあるため「Configure」のサンプルを追加する必要はありません。
「Custom domain」は空欄のままにします。

APIキー、Secrets、有料APIアカウント、支払方法は登録しません。
`GITHUB_TOKEN` はGitHubが自動提供する作業用認証で、ユーザーが作る有料APIキーではありません。

## 5. 初回のニュース取得と公開を実行する

「Actions」→「朝のブリーフ - 無料収集とWeb配信」→「Run workflow」→ Branch `main` →「Run workflow」。
実行結果を開き、収集・保存・公開の各工程を確認します。

緑色のチェックはプログラムが完了したことを示し、情報の正しさまで保証するものではありません。
公開後、アプリの「設定」→「情報源の取得状況」で取得元ごとの成否も確認します。
新着がない場合と取得失敗は区別されます。

初回の全配信元取得が失敗した場合、架空ニュースは入れません。画面に収集前／失敗が表示され、Actionsは失敗表示になります。

## 6. 公開URLを確認する

「Settings」→「Pages」→「Your site is live at ...」または「Visit site」。
実際に表示されたURLを使います。GitHubの `github.com/...` のコード画面URLではありません。

アカウント名が `Ryoto1513`、リポジトリ名が `asa-brief` の場合の想定:

```text
https://Ryoto1513.github.io/asa-brief/
```

これは公開成功後の想定URLです。作成済み／公開済みという意味ではありません。
`github.io` サイトはHTTPSで利用できます。Pages画面で表示される場合は「Enforce HTTPS」も確認します。

## 7. iPhoneに追加する

iPhoneのSafariで、手順6のHTTPS URLを開きます。ChatGPT内蔵ブラウザやダウンロードしたHTMLではありません。
Safariの共有ボタン（またはページメニュー→共有）→「ホーム画面に追加」。
「ウェブアプリとして開く」が表示される場合はオン。
名前を「朝のブリーフ」にして「追加」。

ホーム画面のアイコンから起動し、ニュースの収集日時と記事の公開日時を確認します。
「ホーム画面に追加」が見つからないときは、共有メニューを下へスクロールし「アクションを編集」を確認します。

## 8. 毎日の更新

設定上、7:35 JSTに朝刊用の収集、8:40 JSTに補完の収集を開始します。
GitHub Actionsは遅延・取りこぼしがあり得るため、8:00ちょうどの公開は保証できません。
8:40の版は8:00時点で読めた版とは異なり、その時点までの情報を含みます。

iPhoneで起動時・一定時間後の復帰時に公開済みデータを再取得します。iPhoneで裏側の定刻実行をさせる設計ではありません。
「最新情報を確認」は公開データを再読込するだけで、GitHubの収集を起動するボタンではありません。
ニュース収集をすぐ実行したい場合はGitHubの「Run workflow」を使います。

このアプリ独自のプッシュ通知はありません。既存のChatGPTの朝8時のタスクは別系統です。
公開リポジトリでは60日間リポジトリ活動がないとスケジュールが停止する仕組みがあります。このアプリは実データと取得状況をコミットしますが、長期故障時などはActionsの有効状態を確認してください。無意味なkeep-alive専用処理は入れていません。

## 9. API料金なしで内容を深く読む

アプリ: 見出し・一次情報への入口・固定の基礎解説・用語・確認点。
ChatGPT: 設定済みの朝8時ニュース解説、または記事内の「調べるための依頼文をコピー」から個別の詳しい調査。

ChatGPTの利用枠や既存契約料金は別に適用されます。アプリからChatGPTの有料APIを呼ばず、ChatGPTの回答をアプリに自動転送する機能もありません。
無料での運用を優先し、独自のAI分析や市場価格を事実のように補完しません。

## 10. よくある問題

- Actionsにワークフローが出ない: `.github/workflows/daily-news.yml` がmainにあるか確認。拡張子や親フォルダの二重化に注意。
- Pagesが404: PagesのSourceがGitHub Actionsか、Deploy工程が成功したか、正しい公開URLか確認。
- Publicチェックで失敗: この版はPublic運用専用。既存のPrivateな研究用リポジトリを公開せず、専用リポジトリを使う。
- git pushが403: ログを読み、当該リポジトリのActions権限・組織ポリシー・branch protectionを確認。保護設定を無条件に解除しない。
- 配信元を取得できない: アプリの設定に取得結果を表示。403/429やサイト変更は時間をおいて手動実行するか、情報源設定を見直す。アクセス制限を回避しない。
- 古い記事が残る: 最新号を再取得し、収集日時・公開日時を見る。全取得失敗時は前の号を保持する設計。直近7日の公式発表は古さのラベルを表示。
- 保存記事がSafariとホーム画面アプリで違う: 保存領域の共有を保証しない設計。普段使う入口を一つに統一。
- ホーム画面に追加できない: Safariで公開HTTPS URLを開いているか確認。ダウンロードHTMLではないことを確認。

## 11. 停止する

自動更新だけを止める: Actions → 対象ワークフロー → メニュー → Disable workflow。
サイト公開も止める: Settings → Pagesの公開解除操作を確認して実行。
既存のChatGPTタスクは別設定なので、このアプリを止めても自動では止まりません。
