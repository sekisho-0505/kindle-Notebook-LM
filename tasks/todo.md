# marge_pngs.py の OCR 対応（2026-09-12 完了）

指示書: `ocr_marge_pngs_implementation_instructions.md`

## やること
- [x] 既存コード・README・依存関係・参照関係の調査
- [x] `marge_pngs.py` を OCR 対応（Tesseract + pytesseract、1ページずつ逐次処理）
- [x] 元画像 + 透明テキストレイヤーの検索可能 PDF を出力
- [x] 既存 PDF はスキップ（上書きしない）
- [x] 進捗表示・日本語エラーメッセージ・1ページでも失敗したら本ごと中止
- [x] `kindless.py` に `--direction right|left` を追加（既存の実行方法は維持）
- [x] ダブルクリック起動用 `.bat` 3 種（右矢印 / 左矢印 / OCR PDF 作成）
- [x] 不要ファイルの `trash-can` 退避（`__pycache__`）＋ `.gitignore`
- [x] `requirements.txt` 作成
- [x] 擬似 OCR エンジンでの動作確認（順序・結合・テキスト層・エラー処理）12項目パス
- [x] Tesseract 本体を導入（winget）＋ jpn/jpn_vert 言語データを追加
- [x] 実データ 3 ページで OCR 精度と Ctrl+F 検索を確認（12/12 語ヒット）
- [x] 日本語が 1 文字ずつ分割される問題を PDF 描画命令の補正で解決
- [x] 縦書きの本が文字化けする問題に対応（本ごとに横書き/縦書きを自動判定）
- [x] 実データ 1 冊（82ページ・縦書き）を最初から最後まで OCR して検証
- [x] README を現状のフローに合わせて全面更新

## 実測（新装版 外資系コンサルが教えるプロジェクトマネジメント / 82ページ・縦書き）
- 所要 4分10秒、PDF 18.9MB（OCR前の旧PDF 22.2MB より小さい）
- 全82ページに画像とテキストあり、総文字数 104,369 字、検索テスト 10/10 語ヒット
- 旧PDFとの画素差 0.4〜3.2/255 = 見た目は実質同一

## レビュー
- 変更は `marge_pngs.py`（全面書き換え）と `kindless.py`（引数処理のみ）に限定。
  `dataclass.py` / `WindowInfo.py` / `wxdialog.py` / `kindless.ini` は未変更。
- 保存先は `kindless.ini` の `base_save_folder` を読むようにし、設定の二重管理を避けた。
- Tesseract の日本語 PDF は 1 文字ごとに空白が入り、そのままでは日本語検索が一切できなかった。
  PDF の描画命令から空白（0020）を取り除き、幅が異常な文字だけ次文字までの距離に合わせて補正する方式で解決。
  `-c preserve_interword_spaces=1` や `--psm 6` では解決しないことを実測で確認済み。
- 縦書きの本は `jpn` だと完全に文字化けする（確信度 47 対 93 で明確に差が出るため、
  中ほどの2ページを両方式で試し読みして自動判定する方式にした）。
- PDF ライブラリは pypdf → PyMuPDF に一本化（上記の補正に必要なため、結合も同じライブラリで行う）。
- 残課題: pypdf など一部の抽出ツールは Tz(横倍率)を無視するため、そちらから見ると空白が残る。
  PDF ビューアの Ctrl+F・文字選択・PyMuPDF 抽出は正常。
