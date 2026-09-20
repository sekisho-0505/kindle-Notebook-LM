from dataclass import KindleSSConfig, read_config
from wxdialog import SimpleDialog, Icon
from WindowInfo import (GetVisibleWindowHandleWithName, IsWindowAlive,
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


def wait_screen_stable(cap: 'CaptureWrapper', timeout: float,
                       interval: float = 0.3, quiet: float = 1.5) -> bool:
    """画面が quiet 秒のあいだ変化しなくなるまで待つ。落ち着いたら True。

    クリックやカーソル移動をすると Kindle がツールバーを出す。これは数秒後に
    自分で消えるが、消えるまでは「表示されたまま静止」しているため、
    一瞬の静止で判断するとツールバーごとキャプチャしてしまう。
    出たまま左右端を測るとキャプチャ範囲も狂う(実測 1918px → 347px)。
    """
    prev = cap.capture()
    stable_since = None
    limit = time.perf_counter() + timeout
    while time.perf_counter() < limit:
        time.sleep(interval)
        cur = cap.capture()
        if np.array_equal(prev, cur):
            now = time.perf_counter()
            if stable_since is None:
                stable_since = now
            elif now - stable_since >= quiet:
                return True
        else:
            stable_since = None
        prev = cur
    return False


def capture(cfg: KindleSSConfig, dir_title: str, page: int, hwnd) -> int:
    """ページを送りながら保存する。戻り値は実際に保存した枚数。"""
    print('Cap start')
    sc_w, sc_h = pag.size()
    cap = CaptureWrapper()

    #キーが Kindle に届く状態を作ってから始める。
    #タイトル入力ダイアログの操作でフォーカスが移っていることがあるため前面に戻し、
    #カーソルは本文の外へ逃がす(本文の上にあるとオーバーレイが出たままになり、
    #矢印キーがページ送りに使われない)。画面のちょうど四隅は pyautogui の
    #フェイルセーフ位置で次のキー操作が落ちるため、少し内側に置く
    SetForeWindow(hwnd)
    time.sleep(cfg.long_wait)

    #キャプチャ範囲は「まだ何も操作していない、動きが止まった画面」で測る。
    #先にクリックやカーソル移動をするとオーバーレイが出てその縁を本の端と
    #誤認し(実測 1918px → 543px)、全画面へ切り替えた直後もレイアウトが
    #動いている最中で誤る(実測 347px)
    wait_screen_stable(cap, cfg.fullscreen_wait)
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
    if rht - lft < imp.shape[1] // 2:
        #検出幅が画面の半分にも満たないのは、本の端ではなくオーバーレイや
        #ライブラリ画面の縁を拾った時。本文が切れて保存されるくらいなら
        #余白ごと撮るほうが安全なので、設定どおりの全幅に戻す
        print('キャプチャ範囲の自動検出に失敗したため、画面全体を使います'
              '(検出幅 {} px)'.format(rht - lft))
        lft, rht = left_bound, right_bound
    
    print(lft, sc_w - rht, imp[int(sc_h / 2) , lft +1])
    comic = True if lft < 60 and sc_w - rht < 60 and max(imp[int(sc_h / 2) , lft +1]) == 0 else False
    ext = '.png' if comic else cfg.file_extension

    #範囲を測り終えてから、キーが効く状態を作る。
    #本文をクリックしてキーボードフォーカスを本文に戻す(ページジャンプ等で
    #フォーカスがシークバー等の UI に移ると矢印キーが一切効かなくなる。
    #実測では Escape も Tab も効かず、本文のクリックだけが復帰手段だった)。
    #左右端のクリックはページ送りになり、下寄りはツールバーのボタンに当たる
    #(実測: 全画面時に本が閉じてライブラリに戻った)ため、画面中央を押す
    pag.click(sc_w // 2, sc_h // 2)
    #クリックするとツールバーが出る。全画面ではカーソルを Kindle の外へ
    #出せず自動では消えないので、同じ場所をもう一度押してトグルで閉じる。
    #Windows のダブルクリック判定(既定 500ms)に入らないよう間隔を空ける
    time.sleep(0.8)
    pag.click(sc_w // 2, sc_h // 2)
    time.sleep(cfg.long_wait)
    #カーソルが本文の上に残るとオーバーレイが出たままになり、矢印キーが
    #ページ送りに使われない。画面の角は pyautogui のフェイルセーフ位置なので
    #少し内側へ逃がし、オーバーレイが消えて静止するまで待つ
    pag.moveTo(sc_w - 10, sc_h - 10)
    #ツールバーが自分で消えるまでは長めに待つ(消えないと本文に重なって写る)
    if not wait_screen_stable(cap, cfg.fullscreen_wait * 3):
        print('WARNING: 画面が落ち着きませんでした。ツールバーが写り込む場合があります。')

    old = np.zeros((sc_h , rht-lft, 3), np.uint8)

    if comic and cfg.trim_after_capture:
        arg = queue.Queue()
        rslt = queue.Queue()
        cv = threading.Condition()
        trim = Margin(cfg.trim_margin_top, cfg.trim_margin_bottom, cfg.trim_margin_left, cfg.trim_margin_right)
        gray = Margin(cfg.grayscale_margin_top, cfg.grayscale_margin_bottom, cfg.grayscale_margin_left, cfg.grayscale_margin_right)
        thr = threading.Thread(args=(cv, arg, trim, gray, rslt, cfg.grayscale_threshold),target=thread)
        thr.start()
  
    #ページ送りの向きは本によって違う。指定した向きで 1 枚も進めなかったら
    #逆向きを一度だけ試す(左右どちらの .bat を使っても本が取れるように)
    nextpage_key = cfg.nextpage_key
    reverse_key = {'left': 'right', 'right': 'left'}.get(nextpage_key)
    tried_reverse = False

    saved = 0
    loop = True
    while loop:
        if not IsWindowAlive(hwnd):
            print('Kindle のウィンドウが閉じられたため、キャプチャを中止しました。')
            sys.exit(1)
        filename = osp.join(dir_title , str(page).zfill(3) + ext)
        start = time.perf_counter()
        while True:
            time.sleep(cfg.capture_wait)
            ss = cap.capture()
            ss = ss[:, lft: rht]

            if not np.array_equal(old, ss):
                break
            if time.perf_counter()- start > cfg.timeout_wait:
                if saved <= 1 and reverse_key and not tried_reverse:
                    #まだ 1 枚も進めていない=向きが逆の可能性が高い
                    tried_reverse = True
                    nextpage_key = reverse_key
                    print('ページが進まないため、ページ送りキーを {} に切り替えて試します。'.format(nextpage_key))
                    pag.press(nextpage_key)
                    start = time.perf_counter()
                    continue
                #画面が変わらなくなった=最終ページ。全画面の後始末は呼び出し側で行う
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

            saved += 1
            print('Page:', page, ' ', ss.shape, time.perf_counter() - start, 'sec')
            page += 1
            #keyDown だけでは押しっぱなしのまま残り、キャプチャ後もキーが
            #押された状態になる。press で必ず離すこと
            pag.press(nextpage_key)

    if comic and cfg.trim_after_capture:
        with cv:
            arg.put(ThreadArgs(True, 0, '', None))
            cv.notify()
        thr.join()

        r : list[ThreadResult] = []
        while not rslt.empty():
            r += [rslt.get()]
        if not r:
            #1 枚も撮れていないとトリム範囲を決められない
            return saved
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
    return saved

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


#保存先フォルダの外を指す名前が入力されたときの案内
unsafe_title_label = """そのタイトルは保存先フォルダの外を指してしまうため使えません。

別のタイトルを入力して、もう一度実行してください。"""


#Kindle のウィンドウが見つからないときの案内
kindle_not_found_label = """Kindle のウィンドウが見つかりません。

Kindle for PC を起動し、最小化されていない状態にしてから
もう一度実行してください。"""


#タイトルを自動取得できなかったときにダイアログへ出す案内
manual_title_label = """タイトルを自動取得できませんでした。
本のタイトルを入力してください。
(空のままだと日付がフォルダ名になります)"""


#全画面にできなかったときの案内
#手で直そうとして Kindle をクリックするとフォーカスが本文から外れるため、
#「触らないでほしい」ことをはっきり伝える
not_fullscreen_label = """WARNING: 全画面にできませんでした。このまま続けます。
  画面の端や時計が一緒に写りますが、キャプチャ自体はできます。
  Kindle をクリックしないでください(フォーカスが本文から外れてページを送れなくなります)。"""


#ページが 1 枚も送れずに終わったときの案内
no_page_turn_label = """ERROR: ページが送られませんでした({} 枚で終了)。

ページ送りキーを押しても画面が変わらなかったため、最終ページと判断して止まりました。
次を確認して、もう一度実行してください。

 1. Kindle が本文を表示しているか(目次・設定・ライブラリ画面になっていないか)
 2. 実行中に Kindle をクリックしていないか
    → クリックするとフォーカスがシークバー等に移り、矢印キーでページが送れなくなります
 3. ページ送りの向きが合っているか(今回は「{}」で試しました)
    → もう片方の矢印キー用の .bat を試してください

画像は保存されています。本当に 1 ページだけの本であれば、
OCR_PDF作成.bat を実行すれば PDF を作れます。"""


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


def wait_until_fullscreen(hwnd, timeout: float) -> bool:
    """全画面になるまで待つ。なったら True。

    Microsoft Store 版の Kindle は F11 を押してから実際に全画面になるまで
    1.5 秒ほどかかる。押した直後に調べると必ず「全画面でない」と判定され、
    実際には成功しているのに警告が出てしまう(そして警告を見たユーザーが
    Kindle を手で操作し、フォーカスが本文から外れてページが送れなくなる)。
    """
    limit = time.perf_counter() + timeout
    while time.perf_counter() < limit:
        if is_fullscreen(hwnd):
            return True
        time.sleep(0.1)
    return is_fullscreen(hwnd)


def is_inside(base: str, target: str) -> bool:
    """target が base フォルダの内側を指しているか(保存先の外を操作しないための確認)。"""
    base_abs = osp.normcase(osp.abspath(base))
    target_abs = osp.normcase(osp.abspath(target))
    return target_abs.startswith(base_abs + os.sep)


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
    #Windows はフォルダ名末尾の「.」と空白を扱えない
    title = title.rstrip(' .')
    #空、空白のみ、「.」「..」のようにドットだけの名前は、保存先の外や
    #保存先そのものを指してしまうため使わない(削除事故になる)
    if not title.strip(' .'):
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


def print_banner(cfg: KindleSSConfig, ocr: bool) -> None:
    """実行内容の見出しを出す。

    .bat 側に日本語で書くと、chcp 65001 を通したあとに cmd.exe が
    行の途中から読み直して壊れる(「'CR' は認識されていません」等)ため、
    表示はすべて Python 側で行う。
    """
    arrow = {'left': '左矢印', 'right': '右矢印'}.get(cfg.nextpage_key, cfg.nextpage_key)
    print('=' * 40)
    print(' Kindle キャプチャ({}でページ送り)'.format(arrow))
    print('=' * 40)
    print()
    print('Kindle for PC で本を開いた状態で実行してください。')
    if ocr:
        print('キャプチャ後、そのまま OCR して PDF まで作ります。')
    print()


def main():
    args = parse_args(sys.argv[1:])

    cfg : KindleSSConfig = read_config(KindleSSConfig(), args.ini)
    if args.direction:
        #実行時の指定を優先する(ini は書き換えない)
        cfg.nextpage_key = args.direction
    print_banner(cfg, args.ocr)
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
        #Store 版は切り替えに 1.5 秒ほどかかるため、待ってから判定する
        if not wait_until_fullscreen(ghwnd, cfg.fullscreen_wait):
            print(not_fullscreen_label)

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
    if not is_inside(cfg.base_save_folder, dir_title):
        #ここに来るのは想定外だが、保存先の外を削除しないよう必ず止める
        if entered_fullscreen:
            pag.press(cfg.fullscreen_key)
            time.sleep(cfg.long_wait)
        SimpleDialog.information(title="エラー", label=unsafe_title_label, icon=Icon.Exclamation)
        sys.exit()
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
    saved = capture(cfg, dir_title, page, ghwnd)

    #自分で全画面にしたときだけ元に戻す(元から全画面だった人の状態は変えない)
    if entered_fullscreen and is_fullscreen(ghwnd):
        pag.press(cfg.fullscreen_key)
        time.sleep(cfg.long_wait)

    if saved <= 1:
        #1 枚で「成功」と言うと失敗が隠れる。原因と対処を出して失敗として終わる
        print()
        print(no_page_turn_label.format(saved, cfg.nextpage_key))
        sys.exit(1)

    if args.ocr and not run_ocr(dir_title, rebuild=append):
        sys.exit(1)


def print_result(code: int) -> None:
    """終了結果を表示する(.bat に日本語を書くと cmd.exe が行を壊すため Python 側で出す)。"""
    print()
    print('-' * 40)
    if code == 0:
        print('[成功] 正常に終了しました。')
    else:
        print('[失敗] エラーで終了しました。上に出ている ERROR の行を確認してください。')
    print()
    print('Enter キーでこの画面を閉じます。')


if __name__ == "__main__":
    exit_code = 0
    try:
        main()
    except SystemExit as e:
        exit_code = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
    print_result(exit_code)
    sys.exit(exit_code)