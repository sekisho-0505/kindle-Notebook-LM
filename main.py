# ocr_to_gdoc.py

import os
from pathlib import Path
from typing import List

# --- 画像化＆OCR ---
from pdf2image import convert_from_path
from PIL import Image, ImageOps, ImageFilter
import pytesseract

# --- Markdown→HTML ---
import markdown

# --- Google Drive API ---
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# ===== 設定 =====
PDF_PATH = "input.pdf"                    # ここにOCRしたいPDF
OUTPUT_MD = "output.md"                   # 出力Markdown
TEMP_DIR = Path("./_tmp_ocr")             # 作業用
DOC_TITLE = "OCR取り込み（縦書き）"        # Googleドキュメント名
LANG = "jpn_vert"                         # 日本語縦書き
PSM = 5                                   # 5 or 6 を試す
DPI = 400                                 # 画像化DPI（高め推奨）
# Tesseractの場所が自動認識されない場合は明示（例）：
# pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# ===== Google Drive APIスコープ =====
SCOPES = ["https://www.googleapis.com/auth/drive.file"]
CREDENTIALS_FILE = "credentials.json"  # 事前に配置
TOKEN_FILE = "token.json"

def ensure_dirs():
    TEMP_DIR.mkdir(exist_ok=True)

def pdf_to_images(pdf_path: str, dpi: int) -> List[Path]:
    pages = convert_from_path(pdf_path, dpi=dpi)
    img_paths = []
    for i, page in enumerate(pages, start=1):
        out = TEMP_DIR / f"page_{i:04d}.png"
        page.save(out, "PNG")
        img_paths.append(out)
    return img_paths

def preprocess(img: Image.Image) -> Image.Image:
    # 軽い前処理（グレースケール→コントラスト→軽いシャープ）
    g = ImageOps.grayscale(img)
    g = ImageOps.autocontrast(g)
    g = g.filter(ImageFilter.UnsharpMask(radius=1, percent=150, threshold=3))
    return g

def ocr_image(img_path: Path, lang: str, psm: int) -> str:
    img = Image.open(img_path)
    img = preprocess(img)
    cfg = f"--oem 1 --psm {psm}"
    text = pytesseract.image_to_string(img, lang=lang, config=cfg)
    return text

def to_markdown(pages_text: List[str]) -> str:
    """
    最低限：ページ区切りを入れ、全角中黒・ダッシュ先頭は箇条書きに。
    ※高度なレイアウト復元が不要ならこれで十分実用。
    """
    md_pages = []
    for idx, t in enumerate(pages_text, start=1):
        lines = []
        for raw in t.splitlines():
            s = raw.strip()
            if not s:
                lines.append("")
                continue
            # 簡易: 箇条書き（・/●/○/―/ー など）
            if s.startswith(("・", "●", "○", "ー", "―", "－", "-", "◆", "■")):
                lines.append(f"- {s.lstrip('・●○ー―－-◆■').strip()}")
            else:
                lines.append(s)
        md = "\n".join(lines).strip()
        md_pages.append(f"<!-- Page {idx} -->\n{md}")
    return "\n\n---\n\n".join(md_pages)  # ページ間に水平線

def save_markdown(md: str, out_path: str):
    Path(out_path).write_text(md, encoding="utf-8")

def md_to_html_file(md_path: str) -> Path:
    md_text = Path(md_path).read_text(encoding="utf-8")
    html_text = markdown.markdown(md_text, extensions=["tables", "fenced_code"])
    out_html = Path(md_path).with_suffix(".html")
    out_html.write_text(html_text, encoding="utf-8")
    return out_html

def get_drive_service():
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())  # type: ignore
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "w", encoding="utf-8") as f:
            f.write(creds.to_json())
    return build("drive", "v3", credentials=creds)

def upload_html_as_gdoc(html_file: Path, title: str) -> str:
    """
    Driveの“HTML→Googleドキュメント”自動変換を利用。
    """
    service = get_drive_service()
    file_metadata = {
        "name": title,
        "mimeType": "application/vnd.google-apps.document",
    }
    media = MediaFileUpload(str(html_file), mimetype="text/html", resumable=True)
    created = service.files().create(body=file_metadata, media_body=media, fields="id, webViewLink").execute()
    print("Created Google Doc:", created.get("webViewLink"))
    return created["id"]

def main():
    ensure_dirs()
    print("1/4: PDF → 画像へ変換中...")
    img_paths = pdf_to_images(PDF_PATH, DPI)
    if not img_paths:
        raise RuntimeError("PDFのページが0です")

    print("2/4: 画像 → 日本語縦書きOCR中...")
    texts = []
    for p in img_paths:
        txt = ocr_image(p, LANG, PSM)
        texts.append(txt)

    print("3/4: Markdown生成＆保存...")
    md = to_markdown(texts)
    save_markdown(md, OUTPUT_MD)
    print(f"Markdown保存: {OUTPUT_MD}")

    print("4/4: Googleドキュメントへアップロード（HTML変換→自動変換）...")
    html_path = md_to_html_file(OUTPUT_MD)
    upload_html_as_gdoc(html_path, DOC_TITLE)

    print("完了！")

if __name__ == "__main__":
    main()
