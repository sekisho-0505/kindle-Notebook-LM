# kindle-Notebook-LM

Kindle 書籍のスクリーンショット取得と、PDF を OCR して Google ドキュメントに取り込むまでを自動化するためのツール群です。Windows 上の Kindle for PC での連続キャプチャと、Tesseract OCR を用いた PDF からの文字起こし・アップロード処理を別モジュールとして収めています。

## 主な構成

| ファイル | 役割 |
| --- | --- |
| `kindless.py` | Kindle for PC を操作してページ送りしながらキャプチャを行うメインスクリプト |
| `dataclass.py` | `kindless.py` 用の設定データクラスと INI 読み込み処理 |
| `WindowInfo.py` | Windows API を呼び出して Kindle ウィンドウのハンドルや情報を取得 |
| `wxdialog.py` | ユーザー入力・メッセージ表示用の簡易ダイアログラッパー |
| `kindless.ini` | Kindle キャプチャ機能の設定ファイル |
| `main.py` | PDF → 画像変換 → OCR → Markdown/HTML 化 → Google ドキュメントアップロードを行うスクリプト |

## 必要環境

### 共通

- Python 3.9 以上を推奨
- `pip` で以下のパッケージをインストール

  ```bash
  pip install -U pdf2image pillow pytesseract markdown google-api-python-client \
      google-auth google-auth-oauthlib google-auth-httplib2 opencv-python numpy \
      pyautogui wxPython
  ```

- Microsoft Visual C++ 再頒布可能パッケージ（Windows で OpenCV を利用する際に必要な場合があります）

### Kindle キャプチャ (`kindless.py`)

- Windows 10/11 上の Kindle for PC
- モニター解像度と DPI 設定は Kindle アプリと一致させてください
- 画面全体のキャプチャに `Pillow` の `ImageGrab` を利用するため、リモートセッションでは管理者権限やその他の制限に注意してください

### OCR & Google ドキュメント連携 (`main.py`)

- Tesseract OCR 本体が必要（[公式バイナリ](https://github.com/tesseract-ocr/tesseract) からインストール）。日本語縦書きの場合は `jpn_vert` 言語データを追加します。
- `pdf2image` が内部で利用する [Poppler](https://github.com/oschwartz10612/poppler-windows) のバイナリを PATH に追加するか、`POPPLER_PATH` を環境変数で指定します。
- Google Drive API の OAuth クライアント ID 情報（`credentials.json`）をリポジトリ直下に配置してください。初回実行時にブラウザで認可を行い、`token.json` が生成されます。

## セットアップ手順

1. 本リポジトリをクローンし、必要な Python パッケージをインストールします。
2. Kindle キャプチャを使う場合は `kindless.ini` を環境に合わせて編集します。保存先ディレクトリやショートカットキー、余白調整などを変更できます。
3. OCR ワークフローを使う場合は、OCR したい PDF を `input.pdf`（もしくは `main.py` 内の `PDF_PATH` で指定した名前）として配置し、`credentials.json` を準備します。

## 全体の実行フローと手順

Kindle のキャプチャ取得から OCR・Google ドキュメント反映までを **1 本のファイルで完結させる仕組みではなく**、目的に応じて以下の
2 つのスクリプトを順番に（または必要な方だけを）実行します。

1. `kindless.py` – Kindle for PC からページ送りしながらスクリーンショットを保存
2. `main.py` – 取得済みの PDF（もしくはキャプチャから生成した PDF）を OCR し、Google ドキュメントへアップロード

> キャプチャ画像から PDF を作成する工程は本リポジトリには含まれていないため、必要に応じて外部ツールで PDF 化してください。

### 実行順序の例

- **キャプチャから Google ドキュメントまで行いたい場合**: `kindless.py` を実行して画像を揃え、任意の方法で PDF 化した後、`main.py`
  を実行します。
- **キャプチャのみ必要な場合**: `kindless.py` のみを実行します。
- **OCR・アップロードのみ必要な場合**: 既に用意済みの PDF を `main.py` で処理します。

以下ではそれぞれのスクリプトの詳細な使い方を解説します。

## Kindle キャプチャ機能の使い方

1. Kindle for PC を起動し、キャプチャしたい書籍を表示した状態で `python kindless.py` を実行します。
2. Kindle ウィンドウを検出できない場合はエラーダイアログが表示されます。ウィンドウタイトルと実行ファイル名が `kindless.ini` に設定した値と一致しているか確認してください。
3. 実行するとウィンドウタイトルから自動抽出した書籍名（もしくは `+書籍名` と入力すると既存フォルダに追記）を確認するダイアログが開きます。
4. 指定フォルダ（`base_save_folder/書籍名`）にページ番号付きの画像ファイルが保存されます。コミックの場合はトリミング処理・グレースケール変換が自動で適用されます。

### 主な設定項目

- `nextpage_key` / `fullscreen_key` / `pagejump_key`: Kindle for PC のキーバインドに合わせてください。
- `capture_wait`: ページ送り後にキャプチャを行うまでの待機時間。環境に合わせて調整します。
- `trim_after_capture`: コミック向けの一括トリミング処理を有効化します。
- `grayscale_threshold`: グレースケール判定の閾値。カラーとモノクロを分けて保存したい場合に調整します。
- `base_save_folder`: スクリーンショットを保存するベースディレクトリ。書籍ごとにサブフォルダが作成されます。

## PDF → OCR → Google ドキュメント ワークフロー

`main.py` では以下の流れを自動化しています。

1. **PDF をページごとの PNG 画像へ変換** – `pdf2image.convert_from_path` を利用し、`_tmp_ocr` ディレクトリに出力します。
2. **画像を前処理して OCR** – `Pillow` でグレースケール化・コントラスト調整・軽微なシャープ処理を行い、`pytesseract` で縦書き日本語 (`LANG = "jpn_vert"`) を認識します。
3. **Markdown 生成** – ページごとに Markdown セクションへまとめ、箇条書き風の記号を自動的にリスト化します。
4. **Markdown を HTML に変換** – `markdown` パッケージで HTML に変換し、Google ドライブにアップロードしやすい形式に整えます。
5. **Google ドキュメントへアップロード** – Drive API を用いて HTML ファイルをアップロードし、自動的に Google ドキュメントへ変換します。

実行は以下のコマンドで行います。

```bash
python main.py
```

必要に応じて `PDF_PATH`、`DOC_TITLE`、`LANG`、`PSM`（Tesseract のページ分割モード）などを編集してください。実行中は各ステップの進捗がコンソールに表示され、最後に作成された Google ドキュメントの URL が出力されます。

## トラブルシューティング

- **Kindle ウィンドウを検出できない**: `kindless.ini` の `window_title` と `execute_filename` を確認し、管理者権限で Kindle を起動してみてください。
- **Poppler が見つからないエラー**: `pdf2image` は Poppler に依存します。`pdftoppm.exe` が PATH に入っているか確認します。
- **Tesseract で日本語が認識されない**: `tesseract --list-langs` で `jpn_vert` が表示されるか確認し、`main.py` の `pytesseract.pytesseract.tesseract_cmd` にインストールパスを設定します。
- **Google API 認証でブラウザが開かない**: GUI を持たない環境では `flow.run_local_server()` の代わりに `run_console()` を利用するなど、コードの調整が必要になる場合があります。

## ライセンス

本リポジトリには明示的なライセンスファイルが含まれていません。利用前に作者の意向をご確認ください。
