from pathlib import Path
from PIL import Image
import natsort

def pngs_in(dirpath: Path):
    return natsort.natsorted(dirpath.glob("*.png"), key=lambda p: p.name)

def merge_folder(folder: Path):
    out = folder / f"{folder.name}.pdf"
    if out.exists():
        return 0, f"SKIP: PDF既存 {out.name}"
    pngs = pngs_in(folder)
    if not pngs:
        return 0, f"SKIP: 画像なし {folder}"
    images = [Image.open(p).convert("RGB") for p in pngs]
    images[0].save(out, save_all=True, append_images=images[1:])
    return len(images), f"DONE: {out.name} ({len(images)}ページ)"

def main():
    base = Path("C:/kindle_ss")  # ← kindless.iniで指定した保存先
    for sub in [p for p in base.iterdir() if p.is_dir()]:
        pages, msg = merge_folder(sub)
        print(msg)

if __name__ == "__main__":
    main()

