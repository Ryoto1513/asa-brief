# 朝のブリーフ v1.1 — API料金を使わない版

スマートフォン向けカード型デザインを維持した、個人の非商用ニュース閲覧用PWAです。
**公開・自動運用はまだ開始していません。先に SETUP_ja.md の手順を実行してください。**

## この版でできること

- 公式RSSと、採用する報道機関を限定したニュース検索RSSの見出し収集。
- 日本経済／世界経済／金融政策／政治・地方自治／国際情勢／AI・産業／資産形成の分類。
- 出典・配信元・公開日時・古さ・配信元別の取得成否の表示。
- 見出しに応じた固定の日本語学習ノート、用語説明、原文を読む際の確認点。
- 詳しい調査をChatGPTに頼むための依頼文のコピー（自動送信・API通信なし）。
- 保存・検索・文字サイズ・ダークモード・過去14配信日のアーカイブ。
- 日本時間7:35と8:40にGitHub Actionsを起動し、GitHub Pagesに公開する設定。

## 使わないもの

有料AI API、有料ニュースAPI、有料サーバー、独自ドメイン、APIキー。
LLMへのリクエスト関数とAPIキーの参照は、実行コード・ワークフローから削除しました。
Googleニュース検索RSSは無料で参照する補助経路です。公式の安定APIとしての保証はありません。

## 確認範囲と限界

これは記事ごとのAI分析を毎朝生成するシステムではありません。
**ニュースの見出しと、あらかじめ用意した一般的な学習ノートは別物です。**
本文を読んだような要約、未取得の株価、架空ニュースは表示しません。
許可リストや公式発表ラベルは、内容の真実性・中立性を保証するものではありません。
公式発表と報道を同じ画面で読めますが、同じ事象の独立した複数ソース照合は自動実施していません。
英語の公式発表は原文見出しで表示します。固定の日本語ノートはその翻訳ではありません。

初期データは空です。公開後の最初の取得に成功して初めてニュースが表示されます。
実RSSへの通信・GitHub上の実行・iPhone実機は未検証です。ローカル単体テストと模擬データによる画面検証の範囲は TEST_REPORT.md を参照。

## 読み方

まず見出しで関心のあるニュースを選び、元記事で事実関係を確認します。
その後、アプリ内の一般的な仕組み・用語を読みます。
個別の詳しい検討が必要なら「調べるための依頼文をコピー」から既存のChatGPTを利用します。
ChatGPTの定期タスクとこのアプリは別系統であり、解説結果の自動転送は実装していません。

## 開発用

Python 3.12（標準ライブラリのみ）:

```sh
python -m unittest discover -s tests -v
python tools/update_news.py
python tools/build_site.py
```

`python tools/update_news.py` は外部RSSに接続し、成功すれば `data/` を更新します。
`python tools/update_news.py --dry-run` は外部通信を行いますがファイルは更新しません。
模擬画面テストは `tests/browser_smoke.py`。PlaywrightとChromiumが別途必要です。日々のGitHub Actionsでは実行しません。

## 情報源・運用

`config/sources.json`：情報源、報道機関ドメインの許可リスト、記事数や古さの制限。
`config/knowledge.json`：固定の学習ノート。自動生成・自動更新ではありません。
`data/status.json`：最終試行・配信元別取得結果。全取得失敗時も正常号を保持します。

元記事本文・写真を転載せず、見出しとリンクを中心にしています。RSS公開は無制限の再利用許可を意味しません。情報源を追加・公開用途を変更する際は各配信元の利用条件を確認してください。有料記事やアクセス制限を回避しません。

公開リポジトリと公開サイトは他の人も閲覧できます。氏名・保有銘柄・資産額・認証情報は載せないでください。
個人の保存記事はブラウザの保存領域に置き、サーバーへ送信しません。Safari、ホーム画面アプリ、他の端末の間で保存状態が共有される保証はありません。

## 根拠となる公式資料（2026-10-22確認）

- GitHub Pages: https://docs.github.com/en/pages/getting-started-with-github-pages/what-is-github-pages
- 公開リポジトリの標準Actions実行枠: https://docs.github.com/en/actions/concepts/billing-and-usage
- GitHub Pagesカスタム公開: https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages
- スケジュール遅延・60日無活動停止: https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows
- iPhoneへの追加: https://support.apple.com/ja-jp/guide/iphone/iphea86e5236/ios
- 財務省RSS: https://www.mof.go.jp/about_mof/rss/index.html
- 金融庁RSS: https://www.fsa.go.jp/kouhou/rss.html
- 日本銀行RSS案内: https://www.boj.or.jp/about/abouthp.htm
- FRB RSS: https://www.federalreserve.gov/feeds/feeds.htm
