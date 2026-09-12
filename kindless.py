from dataclass import KindleSSConfig, read_config
from wxdialog import SimpleDialog, Icon
from WindowInfo import (GetWindowHandleWithName, GetVisibleWindowHandleWithName,
                        SetForeWindow, GetWindowText, GetWindowRect)

import argparse
import threading, queue
import sys, os, os.path as osp, datetime , time
import shutil
import dataclasses

import pyautogui as pag
import cv2, numpy as np
from PIL import ImageGrab

rep_list = [['　',' '],[':','：'],[';','；'],['（','('],['）',')'],['［','['],['］',']'],
            ['&','＆'],['"','”'],['|','｜'],['?','？'],['!','！'],['*','＊'],['\\','￥'],
            ['<','＜'],['>','＞'],['/','／']]

@dataclasses.dataclass
class Margin:
    top : int
    bottom : int
    left : int
    right : int

@dataclasses.dataclass
class ThreadArgs:
    endflag : bool
    page : int
    filename : str
    image : np.ndarray

@dataclasses.dataclass
class ThreadResult:
    margin_left : int
    margin_right : int
    gray : bool
    filename : str


class CaptureWrapper:
    def __init__(self):
        pass
    def capture(self) -> np.ndarray:
        cap = ImageGrab.grab()
        return cv2.cvtColor(np.array(cap), cv2.COLOR_RGB2BGR)


def imread(filename: str, flags=cv2.IMREAD_COLOR, dtype=np.uint8) -> np.ndarray:
    n = np.fromfile(filename, dtype)
    img = cv2.imdecode(n, flags)
    return img


def imwrite(filename: str, img : np.ndarray, params=None) -> bool:
    ext = os.path.splitext(filename)[1]
    result, n = cv2.imencode(ext, img, params)
    if result:
        with open(filename, mode='w+b') as f:
            n.tofile(f)
        return True
    else:
        return False


def trim_check(img: np.ndarray, color, margin: Margin):
    def cmps(img, xrange, yrange , color, xdef):
        rt = xdef
        for x in xrange:
            if (img[yrange[0]:yrange[1] , x] != color).any():
                rt = x
                break
        return rt
    
    sx, sy = img.shape[1], img.shape[0]
    #正しい対応:xはleft/right、yはtop/bottom
    x_start, x_end = margin.left, sx - margin.right
    y_start, y_end = margin.top, sy - margin.bottom
    lm = cmps(img, range(x_start, x_end), (y_start, y_end),color, sx)
    if lm == x_start:
        lm = 0
    rm = cmps(img, reversed(range(x_start, x_end)), (y_start, y_end), color, 0)
    if rm == x_end:
        rm = sx
    return lm,rm


def color_check(img: np.ndarray, mg:Margin) -> int:
    imx = img.shape[1]
    imy = img.shape[0]
    img_blue, img_green, img_red = cv2.split(img[mg.top : imy - mg.bottom, mg.left : imx - mg.right])
    img_bg = np.abs(img_blue.astype(int) - img_green.astype(int))
    img_gr = np.abs(img_green.astype(int) - img_red.astype(int))
    img_rb = np.abs(img_red.astype(int) - img_blue.astype(int))
    return max(img_bg.max(),img_gr.max(),img_rb.max()) 


def capture(cfg: KindleSSConfig, dir_title: str, page: int):
    print('Cap start')
    sc_w, sc_h = pag.size()

    cap = CaptureWrapper()
    imp = cap.capture()

    def cmps(img,rng, default):
        for i in rng:
            if np.any(img[20][i] != img[19][0]):
                return i
        return default

    left_bound = cfg.left_margin
    right_bound = imp.shape[1] - cfg.right_margin
    lft = cmps(imp, range(left_bound, right_bound), left_bound)
    rht = cmps(imp, reversed(range(left_bound, right_bound)), right_bound)
    if rht <= lft:
        #フォールバック：全幅扱い
        lft, rht = 0, imp.shape[1]
    
    print(lft, sc_w - rht, imp[int(sc_h / 2) , lft +1])
    comic = True if lft < 60 and sc_w - rht < 60 and max(imp[int(sc_h / 2) , lft +1]) == 0 else False
    ext = '.png' if comic else cfg.file_extension

    old = np.zeros((sc_h , rht-lft, 3), np.uint8)

    if comic and cfg.trim_after_capture:
        arg = queue.Queue()
        rslt = queue.Queue()
        cv = threading.Condition()
        trim = Margin(cfg.trim_margin_top, cfg.trim_margin_bottom, cfg.trim_margin_left, cfg.trim_margin_right)
        gray = Margin(cfg.grayscale_margin_top, cfg.grayscale_margin_bottom, cfg.grayscale_margin_left, cfg.grayscale_margin_right)
        thr = threading.Thread(args=(cv, arg, trim, gray, rslt, cfg.grayscale_threshold),target=thread)
        thr.start()
  
    loop = True
    while loop:
        if GetWindowHandleWithName(cfg.window_title, cfg.execute_filename) == None:
            sys.exit()
        filename = osp.join(dir_title , str(page).zfill(3) + ext)
        start = time.perf_counter()
        while True:
            time.sleep(cfg.capture_wait)
            ss = cap.capture()
            ss = ss[:, lft: rht]

            if not np.array_equal(old, ss):
                break
            if time.perf_counter()- start > cfg.timeout_wait:
                pag.press(cfg.fullscreen_key)
                loop = False
                break
        if loop:
            old = ss.copy()
            if cfg.trim_after_capture and not comic:
                #その場保存(グレースケール判定)
                if color_check(ss, Margin(0,0,0,0)) <= cfg.grayscale_threshold:
                    imwrite(filename,ss[:,:,1])
                else:
                    imwrite(filename,ss)
            elif cfg.trim_after_capture and comic:
                #スレッドに渡す(cvはこの条件でのみ定義済み)
                with cv:
                    arg.put(ThreadArgs( False, page, filename, ss ))
                    cv.notify()
            else:
                #トリムを使わない処理
                imwrite(filename, ss)

            print('Page:', page, ' ', ss.shape, time.perf_counter() - start, 'sec')
            page += 1
            pag.keyDown(cfg.nextpage_key)

    if comic and cfg.trim_after_capture:
        with cv:
            arg.put(ThreadArgs(True, 0, '', None))
            cv.notify()
        thr.join()

        r : list[ThreadResult] = []
        while not rslt.empty():
            r += [rslt.get()]
        ml = min([x.margin_left for x in r])
        mr = max([x.margin_right for x in r])
        print('trim =', ml, mr)
        for i in r:
            print(i.filename, end='')
            s = imread(i.filename)
            s = s[:,ml:mr]
            if i.gray:
                s = cv2.cvtColor(s, cv2.COLOR_RGB2GRAY)
                print(' is grayscale', end = '')
            fn = osp.splitext(i.filename)[0] + cfg.file_extension
            os.remove(i.filename)
            imwrite(fn,s)
            print()
    return

def thread(cv: threading.Condition, que: queue.Queue, trm: Margin, gray: Margin, out: queue.Queue,gs : int):
    end_flag = False
    sc_w, sc_h = pag.size()
    ml = sc_w
    mr = 0
    while not end_flag:
        while not que.empty():
            arg : ThreadArgs = que.get()
            if arg.endflag:
                end_flag = True
                break
            tm = trim_check(arg.image, arg.image[1, 1],trm)
            ml = min(ml, tm[0])
            mr = max(mr, tm[1])
            gst = Margin(gray.top, gray.bottom, gray.left + ml, mr - gray.right)
            gr = (color_check(arg.image, gst) <= gs)
            imwrite(arg.filename, arg.image)
            rslt = ThreadResult(tm[0], tm[1], gr, arg.filename)
            out.put(rslt)
        else:
            with cv:
                cv.wait()


#ウィンドウタイトルに現れるアプリ名(書名ではないと判断するための一覧)
app_name_list = ['Kindle', 'Kindle for PC', 'Kindle for Windows', 'Amazon Kindle']


#Kindle のウィンドウが見つからないときの案内
kindle_not_found_label = """Kindle のウィンドウが見つかりません。

Kindle for PC を起動し、最小化されていない状態にしてから
もう一度実行してください。"""


#タイトルを自動取得できなかったときにダイアログへ出す案内
manual_title_label = """タイトルを自動取得できませんでした。
本のタイトルを入力してください。
(空のままだと日付がフォルダ名になります)"""


def extract_book_title(window_text: str) -> str:
    """ウィンドウタイトルから書名を取り出す。取り出せなければ空文字を返す。

    旧 Kindle for PC は「〇〇 - 書名」の形式でタイトルに書名が入っていたが、
    Microsoft Store 版の新しい Kindle アプリはタイトルが「Kindle」固定で
    書名が入らない。その場合は空文字を返し、呼び出し側で手入力してもらう。
    """
    text = window_text.strip()
    for sep in (' - ', ' – ', ' — ', ' | '):
        if sep in text:
            before, _, after = text.partition(sep)
            #従来どおり区切りの後ろを書名とみなす。後ろがアプリ名なら前を使う。
            for candidate in (after.strip(), before.strip()):
                if candidate and candidate not in app_name_list:
                    return candidate
            return ''
    return '' if text in app_name_list else text


def sanitize_title(title: str) -> str:
    """フォルダ名に使えない文字を全角などに置き換える。"""
    for i in rep_list:
        title = title.replace(i[0], i[1])
    return title.strip()


def is_fullscreen(hwnd) -> bool:
    """ウィンドウが画面全体を覆っているか(最大化とは区別する)。"""
    left, top, right, bottom = GetWindowRect(hwnd)
    sc_w, sc_h = pag.size()
    return (right - left) >= sc_w and (bottom - top) >= sc_h


def resolve_folder_name(entered: str) -> tuple[str, bool]:
    """入力されたタイトルから、保存フォルダ名と追記フラグ(+)を決める。

    空のまま OK されると保存先フォルダ自体を削除してしまうため、
    必ず何らかの名前を返す(最後の手段として日付を使う)。
    """
    title = (entered or '').strip()
    append = title.startswith('+')
    if append:
        title = title[1:]
    title = sanitize_title(title)
    if not title:
        return datetime.datetime.now().strftime("%Y_%m_%d_%H_%M_%S"), False
    return title, append


def run_ocr(dir_title: str, rebuild: bool) -> bool:
    """キャプチャした本だけを OCR して PDF を作る(--ocr 指定時)。成功なら True。"""
    from pathlib import Path
    import marge_pngs                      #OCR を使うときだけ読み込む

    folder = Path(dir_title)
    out = folder / (folder.name + '.pdf')
    print()
    print('=' * 40)
    print('続けて OCR して PDF を作ります')
    print('=' * 40)
    print()
    if rebuild and out.exists():
        #追記した場合、既存 PDF はページが足りないので作り直す
        print('ページを追記したため、古い PDF を作り直します:', out.name)
        out.unlink()
    try:
        lang, vertical_lang = marge_pngs.check_tesseract()
        return marge_pngs.merge_folder(folder, lang, vertical_lang, [])
    except SystemExit:
        print()
        print('PNG の保存は完了しています。')
        print('Tesseract を用意してから OCR_PDF作成.bat を実行すれば PDF を作れます。')
    except Exception as e:
        print()
        print('OCR に失敗しました:', e)
        print('PNG の保存は完了しています。OCR_PDF作成.bat でやり直せます。')
    return False


def parse_args(argv: list[str]) -> argparse.Namespace:
    #従来どおり ini ファイル名も指定できる(省略時は kindless.ini)
    parser = argparse.ArgumentParser(description='Kindle for PC の画面を連続キャプチャします')
    parser.add_argument('ini', nargs='?', default='kindless.ini',
                        help='設定ファイル (省略時: kindless.ini)')
    parser.add_argument('--direction', choices=['right', 'left'], default=None,
                        help='ページ送りに押す矢印キー。省略時は ini の nextpage_key を使う')
    parser.add_argument('--ocr', action='store_true',
                        help='キャプチャ完了後に、その本だけ OCR して PDF を作る')
    return parser.parse_args(argv)


def main():
    args = parse_args(sys.argv[1:])

    cfg : KindleSSConfig = read_config(KindleSSConfig(), args.ini)
    if args.direction:
        #実行時の指定を優先する(ini は書き換えない)
        cfg.nextpage_key = args.direction
    print('ページ送りキー:', cfg.nextpage_key)
    #非表示のまま残っている古いウィンドウを掴まないよう、表示中のものから選ぶ
    ghwnd = GetVisibleWindowHandleWithName(cfg.window_title, cfg.execute_filename)
    if ghwnd == None:
        SimpleDialog.information(title="エラー", label=kindle_not_found_label, icon=Icon.Exclamation)
        sys.exit()
    print('対象ウィンドウ:', GetWindowText(ghwnd))

    t = sanitize_title(extract_book_title(GetWindowText(ghwnd)))
    if not cfg.auto_title:
        t = ''
    if t:
        dialog_label = "タイトルを確認してください"
    else:
        dialog_label = manual_title_label
    SetForeWindow(ghwnd)
    time.sleep(cfg.short_wait)
    if cfg.force_move_first_page:
        pag.hotkey(*cfg.pagejump_key)
        time.sleep(cfg.short_wait)
        pag.press(cfg.pagejump)
        pag.press('enter')
        time.sleep(cfg.capture_wait)

    #すでに全画面ならキーを押さない(押すと逆に解除されてしまう)
    entered_fullscreen = not is_fullscreen(ghwnd)
    if entered_fullscreen:
        pag.press(cfg.fullscreen_key)
        time.sleep(cfg.long_wait)
    if not is_fullscreen(ghwnd):
        print('WARNING: 全画面になりませんでした。手動で全画面にしてから OK を押してください。')

    sc_w, sc_h = pag.size()
    pag.moveTo(sc_w / 2, sc_h / 2)
    ok, book_title = SimpleDialog.askstring(title="タイトル入力", label=dialog_label, value=t, width=400)
    if not ok:
        if entered_fullscreen:
            pag.press(cfg.fullscreen_key)
            time.sleep(cfg.long_wait)
        sys.exit()
    book_title, append = resolve_folder_name(book_title)

    dir_title = osp.join(cfg.base_save_folder,book_title)
    print(dir_title)
    page = 1
    if osp.exists(dir_title):
        if append:
            page = max([int(os.path.splitext(os.path.basename(i))[0])
                    for i in os.listdir(dir_title)]) + 1 if append else 1
        elif cfg.overwrite:
            shutil.rmtree(dir_title)
            os.makedirs(dir_title)
        else:
            if entered_fullscreen:
                pag.press(cfg.fullscreen_key)
                time.sleep(cfg.long_wait)
            SimpleDialog.information(title="エラー", label="ディレクトリが存在します", icon=Icon.Exclamation)
            sys.exit()
    else:
        try:
            os.makedirs(dir_title)
        except OSError as e:
            if entered_fullscreen:
                pag.press(cfg.fullscreen_key)
                time.sleep(cfg.long_wait)
            SimpleDialog.information(title="エラー", label="ディレクトリが作成できませんでした", icon=Icon.Exclamation)
            sys.exit()
    time.sleep(cfg.fullscreen_wait)
    capture(cfg, dir_title, page)
    if args.ocr and not run_ocr(dir_title, rebuild=append):
        sys.exit(1)


if __name__ == "__main__":
    main()