# -*- coding: utf-8 -*-
"""capture() のページ送りループを、画面と入力を偽物に差し替えて検証する。

    python tests/test_capture_loop.py

実機（Kindle）なしで動く。pyautogui と ImageGrab を差し替えるだけなので、
Kindle が起動していなくても、本を開いていなくても実行できる。

確かめること:
  1. 複数ページを最後まで撮れる（1 ページで止まらない）
  2. 戻り値が実際に保存した枚数と一致する
  3. ページ送りに press() を使い、押しっぱなしの keyDown() を使っていない
     （keyDown だけだと終了後も矢印キーが押された状態で残る）
  4. 開始時に前面化し、本文をクリックし、カーソルを本文の外へ逃がしている
     （フォーカスが外れると矢印キーが効かず、カーソルが本文上だとオーバーレイが出る）
  5. ページが 1 枚も送れないときに 1 を返す（呼び出し側が失敗と判定できる）
  6. wait_until_fullscreen() が「遅れて全画面になる」ケースを拾える
     （Store 版 Kindle は F11 から全画面まで実測 1.5 秒かかる）
  7. wait_screen_stable() が「一定時間ずっと変化がない」ことを条件にしている
  8. ページ送りの向きが逆でも、自動で逆向きに切り替えて撮り切れる

経緯と注意は tasks/lessons.md の L-007 を参照。
"""
import os
import shutil
import sys
import tempfile

import numpy as np
from PIL import Image

#テストの 1 つ上がリポジトリのルート
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import kindless
from dataclass import KindleSSConfig

W, H = 200, 100


class FakePag:
    """pyautogui の代わり。押されたキーを記録し、press でページを進める。"""

    def __init__(self, screen):
        self.screen = screen
        self.pressed = []
        self.key_down = []
        self.key_up = []
        self.moved_to = []
        self.clicked = []

    def size(self):
        return (W, H)

    def press(self, key):
        self.pressed.append(key)
        self.screen.turn_page(key)

    def keyDown(self, key):
        self.key_down.append(key)

    def keyUp(self, key):
        self.key_up.append(key)

    def moveTo(self, x, y):
        self.moved_to.append((x, y))

    def click(self, x, y):
        self.clicked.append((x, y))

    def hotkey(self, *keys):
        pass


class FakeScreen:
    """ページごとに違う画像を返す偽の画面。最終ページ以降は変化しない。"""

    def __init__(self, total_pages, forward_key='right'):
        self.total = total_pages
        self.page = 0
        self.forward_key = forward_key

    def turn_page(self, key=None):
        #その本で「進む」向きのキー以外では何も起きない
        if key is not None and key != self.forward_key:
            return
        if self.page < self.total - 1:
            self.page += 1

    def grab(self):
        img = np.full((H, W, 3), 255, np.uint8)
        #ページごとに中央の帯の色を変える（端は白のままにして comic 判定を避ける）
        img[40:60, 40:160] = (10 + self.page * 7) % 200
        return Image.fromarray(img)


class FakeImageGrab:
    def __init__(self, screen):
        self.screen = screen

    def grab(self):
        return self.screen.grab()


def make_cfg(tmp):
    cfg = KindleSSConfig()
    cfg.left_margin = 1
    cfg.right_margin = 1
    cfg.capture_wait = 0.01
    cfg.timeout_wait = 0.15
    cfg.long_wait = 0.0
    cfg.short_wait = 0.0
    cfg.trim_after_capture = False
    cfg.file_extension = '.png'
    cfg.nextpage_key = 'right'
    return cfg


def run_capture(total_pages, tmp, forward_key='right', next_key='right'):
    screen = FakeScreen(total_pages, forward_key)
    fake_pag = FakePag(screen)
    calls = {'fore': 0}

    kindless.pag = fake_pag
    kindless.ImageGrab = FakeImageGrab(screen)
    kindless.SetForeWindow = lambda hwnd: calls.__setitem__('fore', calls['fore'] + 1)
    kindless.IsWindowAlive = lambda hwnd: True

    cfg = make_cfg(tmp)
    cfg.nextpage_key = next_key
    saved = kindless.capture(cfg, tmp, 1, hwnd=1234)
    return saved, fake_pag, calls


def main():
    failures = []

    def check(cond, label):
        print('  {}  {}'.format('OK  ' if cond else 'NG  ', label))
        if not cond:
            failures.append(label)

    tmp = tempfile.mkdtemp(prefix='capture_test_')
    try:
        print('[1] 5 ページの本を最後まで撮れるか')
        saved, fp, calls = run_capture(5, tmp)
        files = sorted(f for f in os.listdir(tmp) if f.endswith('.png'))
        check(saved == 5, '戻り値が 5（実際: {}）'.format(saved))
        check(len(files) == 5, 'PNG が 5 枚保存された（実際: {} 枚 {}）'.format(len(files), files))
        check(files == ['001.png', '002.png', '003.png', '004.png', '005.png'],
              'ファイル名が 001〜005 の連番')
        print()

        print('[2] ページ送りの送り方')
        check(len(fp.key_down) == 0,
              '押しっぱなしの keyDown を使っていない（実際: {} 回）'.format(len(fp.key_down)))
        check(all(k == 'right' for k in fp.pressed) and len(fp.pressed) >= 4,
              'press("right") でページを送っている（実際: {} 回）'.format(len(fp.pressed)))
        print()

        print('[3] キャプチャ開始時の下ごしらえ')
        check(calls['fore'] >= 1, '前面化（SetForeWindow）を呼んでいる')
        #カーソルを本文の外へ逃がさないとオーバーレイが出たままになり、
        #矢印キーがページ送りに使われない（実機で 38枚 → 1枚に落ちた）
        check(fp.moved_to and fp.moved_to[0] == (W - 10, H - 10),
              'カーソルを本文の外へ逃がしている（実際: {}）'.format(fp.moved_to[:1]))
        #ただし画面の角ちょうどだと次のキー操作が FailSafeException で落ちる
        import pyautogui as real_pag
        sw, sh = real_pag.size()
        target = (sw - 10, sh - 10)
        check(target not in list(real_pag.FAILSAFE_POINTS),
              '退避先 {} がフェイルセーフ位置に当たらない'.format(target))
        #フォーカスが本文から外れていると矢印キーが一切効かない。
        #実測で Escape も Tab も効かず、本文のクリックだけが復帰手段だった
        check(fp.clicked and fp.clicked[0] == (W // 2, H // 2),
              '本文をクリックしてフォーカスを戻している（実際: {}）'.format(fp.clicked[:1]))
        print()

        print('[4] 1 ページも送れない本（元の不具合と同じ状況）')
        shutil.rmtree(tmp)
        os.makedirs(tmp)
        saved1, _, _ = run_capture(1, tmp)
        check(saved1 == 1, '戻り値が 1 で、呼び出し側が失敗と判定できる（実際: {}）'.format(saved1))
        print()

        print('[5] 遅れて全画面になるケースを拾えるか')
        state = {'n': 0}

        def delayed_fullscreen(hwnd):
            #4 回目の問い合わせで初めて全画面になる（Store 版の 1.5 秒遅延を模す）
            state['n'] += 1
            return state['n'] >= 4

        real_is_fullscreen = kindless.is_fullscreen
        kindless.is_fullscreen = delayed_fullscreen
        try:
            check(kindless.wait_until_fullscreen(1234, timeout=3.0) is True,
                  '遅れて全画面になっても True を返す（旧コードは即 False で誤警告）')
            state['n'] = 0
            kindless.is_fullscreen = lambda hwnd: False
            check(kindless.wait_until_fullscreen(1234, timeout=0.3) is False,
                  '本当に全画面にならない場合は False を返す')
        finally:
            kindless.is_fullscreen = real_is_fullscreen
        print()

        print('[6] オーバーレイが消える（画面が静止する）まで待てるか')

        class Settling:
            """n 回だけ変化し、その後は同じ画面を返す。"""

            def __init__(self, n):
                self.n = n

            def capture(self):
                self.n -= 1
                return np.full((4, 4, 3), max(self.n, 0), np.uint8)

        class NeverSettles:
            def __init__(self):
                self.n = 0

            def capture(self):
                self.n += 1
                return np.full((4, 4, 3), self.n % 250, np.uint8)

        check(kindless.wait_screen_stable(Settling(3), timeout=3.0, interval=0.05) is True,
              '変化が止まったら True を返す（オーバーレイが消えた）')
        check(kindless.wait_screen_stable(NeverSettles(), timeout=0.4, interval=0.05) is False,
              '変化し続けたら時間切れで False を返す（無限に待たない）')
        print()

        print('[7] 指定した向きが逆でも自動で切り替えられるか')
        shutil.rmtree(tmp)
        os.makedirs(tmp)
        #この本は right で進むのに、left を指定して実行した場合
        saved7, fp7, _ = run_capture(5, tmp, forward_key='right', next_key='left')
        check(saved7 == 5, '逆向きを指定しても最後まで撮れる（実際: {} 枚）'.format(saved7))
        check('left' in fp7.pressed and 'right' in fp7.pressed,
              '効かない向きを検知して逆向きへ切り替えた（押した順: {}）'.format(fp7.pressed))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    print('=' * 52)
    if failures:
        print(' 失敗 {} 件:'.format(len(failures)))
        for f in failures:
            print('   - {}'.format(f))
        return 1
    print(' すべてのチェックに通りました')
    return 0


if __name__ == '__main__':
    sys.exit(main())
