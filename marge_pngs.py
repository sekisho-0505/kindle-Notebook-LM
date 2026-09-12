"""Kindle のスクリーンショット(PNG)を OCR して、文字検索できる PDF にまとめる。

使い方:
    python marge_pngs.py
    (または OCR_PDF作成.bat をダブルクリック)

保存先フォルダの中にある書籍フォルダを 1 つずつ処理し、
「書籍フォルダ名.pdf」を同じフォルダの中に作成する。
既に PDF がある書籍はスキップする(上書きしない)。
"""

import configparser
import os
import re
import shutil
import sys
import time
from pathlib import Path

import fitz  # PyMuPDF
import natsort
import pytesseract
from PIL import Image
from pytesseract import Output

# ---------------- 設定 ----------------
# kindless.ini が読めない場合に使う保存先
BASE_DIR = Path("C:/kindle_ss")
# OCR に使う言語(日本語 + 英語)
OCR_LANG = "jpn+eng"
# 縦書きの本に使う言語と設定(小説・ビジネス書などに多い)
OCR_LANG_VERTICAL = "jpn_vert+eng"
VERTICAL_CONFIG = "--psm 5"
# 縦書き判定: 確信度がこの値より高ければ縦書きとみなす
VERTICAL_MARGIN = 5.0
# Tesseract が PATH にない場合に探す場所
TESSERACT_CANDIDATES = [
    Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
    Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"),
    Path(os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe")),
]
# --------------------------------------

# --- 日本語の「1文字ごとの空白」を取り除くための設定 -------------------
# Tesseract は日本語を1文字ずつ単語として扱い、PDF のテキスト層に
# 「文字 + 空白」を書き込む。そのままだと「追 加 実 装」となり、
# Ctrl+F で「追加実装」を検索してもヒットしない。
# そこで PDF の描画命令から、日本語だけの単語の後ろの空白を取り除く。
_CJK = re.compile(r"[\u3000-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uff00-\uffef]")
_ASCII = re.compile(r"[0-9A-Za-z]")
# 「/f-0-0 34 Tf」= 文字サイズ指定、「968 Tz [ <8FFD0020> ] TJ 48 0 Td」= 1文字の描画
_TOKEN = re.compile(
    rb"/f-[0-9-]+\s+([0-9.]+)\s+Tf"
    rb"|([0-9.]+)\s+Tz\s*\[\s*<([0-9A-Fa-f]+)>\s*\]\s*TJ(?:\s+(-?[0-9.]+)\s+0\s+Td)?"
)
_GLYPH_EM = 0.5      # 透明フォント1文字ぶんの幅(em)
_TOO_WIDE = 2.5      # 次の文字までの距離に対し、この倍率より広い文字幅は異常とみなす
_TOO_NARROW = 0.4    # 同じく、この倍率より狭い文字幅は異常とみなす
# ----------------------------------------------------------------------


def resolve_base_dir() -> Path:
    """スクリーンショットの保存先を決める(kindless.ini の設定を優先)。"""
    ini = Path(__file__).with_name("kindless.ini")
    if ini.exists():
        parser = configparser.ConfigParser()
        parser.read(ini, encoding="utf-8")
        folder = parser.get("KINDLESS", "base_save_folder", fallback="").strip()
        if folder:
            return Path(folder)
    return BASE_DIR


def check_tesseract() -> tuple[str, str | None]:
    """Tesseract と言語データを確認し、(横書き用, 縦書き用) の言語名を返す。"""
    # PATH に tesseract が無ければ、よくあるインストール先を探す
    if shutil.which(pytesseract.pytesseract.tesseract_cmd) is None:
        for candidate in TESSERACT_CANDIDATES:
            if candidate.exists():
                pytesseract.pytesseract.tesseract_cmd = str(candidate)
                break

    try:
        pytesseract.get_tesseract_version()
    except Exception:
        print("ERROR:")
        print("Tesseract OCR が見つかりません。")
        print()
        print("Tesseract をインストールし、")
        print("PATH が設定されているか確認してください。")
        print(r"(インストール先の例: C:\Program Files\Tesseract-OCR\tesseract.exe)")
        print("詳しい手順は README.md の「初回セットアップ」を見てください。")
        sys.exit(1)

    try:
        langs = set(pytesseract.get_languages(config=""))
    except Exception:
        # 言語一覧を取得できない場合は、そのまま既定の設定で進める
        return OCR_LANG, None

    if "jpn" not in langs:
        print("ERROR:")
        print("Tesseract の日本語言語データ「jpn」が見つかりません。")
        print()
        print("Tesseract のインストーラを再実行し、")
        print("「Additional language data」から Japanese を追加してください。")
        print(f"(現在使える言語: {', '.join(sorted(langs)) or 'なし'})")
        sys.exit(1)

    if "eng" in langs:
        horizontal, vertical = OCR_LANG, OCR_LANG_VERTICAL
    else:
        print("WARNING: 英語データ「eng」が無いため、日本語のみで OCR します。")
        horizontal, vertical = "jpn", "jpn_vert"
    if "jpn_vert" not in langs:
        print("WARNING: 縦書き用データ「jpn_vert」が無いため、横書きとして OCR します。")
        vertical = None
    return horizontal, vertical


def pngs_in(dirpath: Path) -> list[Path]:
    """フォルダ内の PNG をページ番号順(001, 002, ... 010)に並べて返す。"""
    return natsort.natsorted(dirpath.glob("*.png"), key=lambda p: p.name)


def has_text_layer(pdf_path: Path) -> bool:
    """既存 PDF に文字データが入っているか(先頭 3 ページで判定)。"""
    try:
        with fitz.open(pdf_path) as doc:
            for i in range(min(3, doc.page_count)):
                if doc[i].get_text().strip():
                    return True
    except Exception:
        return True  # 判定できないときは触らない扱いにする
    return False


def ocr_page(png_path: Path, lang: str, config: str = "") -> bytes:
    """1 ページ分の PNG を OCR し、テキスト付き 1 ページ PDF のバイト列を返す。"""
    with Image.open(png_path) as image:
        return pytesseract.image_to_pdf_or_hocr(image, extension="pdf", lang=lang, config=config)


def _mean_confidence(png_path: Path, lang: str, config: str) -> float:
    """1 ページを試し読みして、認識の確からしさ(0-100)の平均を返す。"""
    with Image.open(png_path) as image:
        data = pytesseract.image_to_data(image, lang=lang, config=config, output_type=Output.DICT)
    scores = [int(c) for t, c in zip(data["text"], data["conf"]) if t.strip() and int(c) >= 0]
    return sum(scores) / len(scores) if scores else 0.0


def detect_direction(pngs: list[Path], lang: str, vertical_lang: str | None) -> tuple[str, str]:
    """本の中ほどを試し読みして、横書き用と縦書き用のどちらで読むかを決める。"""
    if not vertical_lang:
        return lang, ""
    # 表紙や目次を避けるため、本の 2/5 と 3/5 あたりのページで判定する
    positions = sorted({len(pngs) * 2 // 5, len(pngs) * 3 // 5})
    samples = [pngs[i] for i in positions]
    try:
        h = sum(_mean_confidence(p, lang, "") for p in samples) / len(samples)
        v = sum(_mean_confidence(p, vertical_lang, VERTICAL_CONFIG) for p in samples) / len(samples)
    except Exception as e:
        print(f"  WARNING: 書き方向を判定できませんでした ({e})。横書きとして進めます。")
        return lang, ""
    print(f"書き方向の判定: 横書き {h:.1f} 点 / 縦書き {v:.1f} 点", end="  ")
    if v > h + VERTICAL_MARGIN:
        print("→ 縦書きの本として OCR します")
        return vertical_lang, VERTICAL_CONFIG
    print("→ 横書きの本として OCR します")
    return lang, ""


def _fix_stream(data: bytes) -> bytes:
    """PDF の描画命令から、日本語1文字ごとの余計な空白を取り除く。"""
    state = {"size": 0.0}

    def replace(m) -> bytes:
        if m.group(1):                       # 文字サイズの指定を覚えておく
            state["size"] = float(m.group(1))
            return m.group(0)
        tz, hexstr, dx = m.group(2), m.group(3), m.group(4)
        try:
            text = bytes.fromhex(hexstr.decode("ascii")).decode("utf-16-be")
        except Exception:
            return m.group(0)
        # 「日本語だけ + 末尾が空白」の単語だけを対象にする(英単語の空白は残す)
        if not (len(text) >= 2 and text.endswith(" ")
                and _CJK.search(text[:-1]) and not _ASCII.search(text[:-1])):
            return m.group(0)

        count = len(text) - 1
        new_tz = float(tz)
        natural = count * _GLYPH_EM * state["size"]
        if dx and natural > 0:
            step = float(dx)                 # 次の文字までの距離
            rendered = natural * new_tz / 100.0
            # 文字幅が極端にずれている場合(主に見出し)だけ、距離に合わせて補正する
            if step > 0 and (rendered > step * _TOO_WIDE or rendered < step * _TOO_NARROW):
                new_tz = step / natural * 100.0

        fixed = b"%.3f Tz [ <%s> ] TJ" % (new_tz, hexstr[:-4])   # 末尾の空白(0020)を削る
        if dx is not None:
            fixed += b" %s 0 Td" % dx
        return fixed

    return _TOKEN.sub(replace, data)


def fix_japanese_spacing(page_pdf: fitz.Document) -> None:
    """OCR 直後の PDF を、日本語を検索できる状態に直す(失敗しても元のまま進む)。"""
    try:
        for page in page_pdf:
            for xref in page.get_contents():
                page_pdf.update_stream(xref, _fix_stream(page_pdf.xref_stream(xref)))
    except Exception as e:
        print(f"  WARNING: 日本語の空白除去をスキップしました ({e})")


def format_elapsed(seconds: float) -> str:
    """経過秒を MM:SS 形式にする。"""
    minutes, sec = divmod(int(seconds), 60)
    return f"{minutes:02d}:{sec:02d}"


def merge_folder(folder: Path, lang: str, vertical_lang: str | None, no_text_pdfs: list[str]) -> bool:
    """書籍フォルダ 1 つを OCR して PDF 化する。成功(スキップ含む)なら True。"""
    out = folder / f"{folder.name}.pdf"
    print("=" * 40)
    print(folder.name)
    print("=" * 40)
    print()

    if out.exists():
        print(f"SKIP: PDF既存 {out.name}")
        if not has_text_layer(out):
            no_text_pdfs.append(folder.name)
            print("  ※この PDF には文字データがありません(OCR 対応前に作られた PDF です)。")
            print("  　OCR し直すには、この PDF を削除してから実行してください。")
        print()
        return True

    pngs = pngs_in(folder)
    if not pngs:
        print(f"SKIP: 画像なし {folder}")
        print()
        return True

    total = len(pngs)
    print(f"{total} PNG files found.")
    ocr_lang, ocr_config = detect_direction(pngs, lang, vertical_lang)
    print()

    start = time.perf_counter()
    book = fitz.open()
    current = pngs[0]
    try:
        for index, png in enumerate(pngs, start=1):
            current = png
            print(f"OCR {index}/{total} : {png.name}", flush=True)
            with fitz.open(stream=ocr_page(png, ocr_lang, ocr_config), filetype="pdf") as page_pdf:
                fix_japanese_spacing(page_pdf)
                book.insert_pdf(page_pdf)
    except Exception as e:
        book.close()
        print()
        print(f"ERROR: {current.name} の OCR に失敗しました")
        print(f"  理由: {e}")
        print(f"  → ページ抜けを防ぐため、{out.name} は作成しませんでした。")
        print()
        return False

    # 途中で失敗しても壊れた PDF を残さないよう、一時ファイルに書いてから置き換える
    tmp = folder / f"{folder.name}.pdf.tmp"
    try:
        book.save(tmp, deflate=True, garbage=3)
        book.close()
        os.replace(tmp, out)
    finally:
        if tmp.exists():
            tmp.unlink()

    print()
    print("DONE:")
    print(out.name)
    print()
    print(f"Pages: {total}")
    print(f"Elapsed: {format_elapsed(time.perf_counter() - start)}")
    print()
    return True


def main() -> int:
    lang, vertical_lang = check_tesseract()
    base = resolve_base_dir()
    if not base.is_dir():
        print("ERROR:")
        print(f"スクリーンショットの保存先フォルダが見つかりません: {base}")
        print("先に kindless.py でキャプチャを行うか、")
        print("kindless.ini の base_save_folder を確認してください。")
        return 1

    print(f"対象フォルダ: {base}")
    print(f"OCR 言語    : {lang}" + (f" / 縦書き用 {vertical_lang}" if vertical_lang else ""))
    print()

    folders = natsort.natsorted([p for p in base.iterdir() if p.is_dir()], key=lambda p: p.name)
    if not folders:
        print(f"処理できる書籍フォルダがありません: {base}")
        return 0

    started = time.perf_counter()
    no_text_pdfs: list[str] = []
    failed = [f.name for f in folders if not merge_folder(f, lang, vertical_lang, no_text_pdfs)]

    print("=" * 40)
    print(f"すべて完了 ({len(folders) - len(failed)}/{len(folders)} 冊 成功)")
    print(f"合計時間: {format_elapsed(time.perf_counter() - started)}")
    if no_text_pdfs:
        print()
        print(f"お知らせ: 文字データの無い PDF が {len(no_text_pdfs)} 冊あります。")
        print("OCR し直したい本は、その本のフォルダにある PDF を削除してから、もう一度実行してください。")
        for name in no_text_pdfs:
            print(f"  - {name}")
    if failed:
        print()
        print("失敗した本:")
        for name in failed:
            print(f"  - {name}")
        return 1
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print()
        print("中断しました。")
        sys.exit(1)
