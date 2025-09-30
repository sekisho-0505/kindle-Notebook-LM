from ctypes import (windll, WINFUNCTYPE, POINTER, c_bool, c_int, c_ulong, pointer, create_unicode_buffer)
from ctypes.wintypes import HWND, RECT
import os.path

EnumWindows = windll.user32.EnumWindows
WNDENUMPROC = WINFUNCTYPE(c_bool, POINTER(c_int), POINTER(c_int))

ignores = ['Default IME', 'MSCTFIME UI']

ghwnd = None
wintitle = ''
pName = None
windowlist = []

# uflags
SWP_ASYNCWINDOWPOS = 0x4000
SWP_DEFERERASE = 0x2000
SWP_DRAWFRAME = 0x0020
SWP_FRAMECHANGED = 0x0020
SWP_HIDEWINDOW = 0x0080
SWP_NOACTIVATE = 0x0010
SWP_NOCOPYBITS = 0x0100
SWP_NOMOVE = 0x0002
SWP_NOOWNERZORDER = 0x0200
SWP_NOREDRAW = 0x0008
SWP_NOREPOSITION = 0x0200
SWP_NOSENDCHANGING = 0x0400
SWP_NOSIZE = 0x0001
SWP_NOZORDER = 0x0004
SWP_SHOWWINDOW = 0x0040

def EnumWindowsProc(hwnd, lParam):
    global ghwnd, wintitle, pname
    length = windll.user32.GetWindowTextLengthW(hwnd)
    buff = create_unicode_buffer(length + 1)
    windll.user32.GetWindowTextW(hwnd, buff, length + 1)
    if buff.value.find(wintitle) != -1:
        if pname is not None:
            p = os.path.basename(GetWindowThreadProcessName(hwnd))
            if p.upper() != pname.upper():
                return True
        ghwnd = hwnd
        return False
    return True

def EnumWindowsListProc(hwnd, lParam):
    global windowlist, ignores
    length = windll.user32.GetWindowTextLengthW(hwnd)
    buff = create_unicode_buffer(length + 1)
    windll.user32.GetWindowTextW(hwnd, buff, length + 1)
    if not any([buff.value.find(x) != -1 for x in ignores]) and buff.value != '':
        windowlist.append({'Text': buff.value, 'HWND': hwnd, 'Pos': GetWindowRect(ghwnd), 'pid': GetWindowThreadProcessId(hwnd) , 'Location': GetWindowThreadProcessName(hwnd)})
    return True

def GetWindowThreadProcessId(hwnd):
    pid = c_ulong()
    windll.user32.GetWindowThreadProcessId(hwnd,pointer(pid))
    return pid.value

def GetWindowThreadProcessName(hwnd):
    pid = c_ulong()
    windll.user32.GetWindowThreadProcessId(hwnd, pointer(pid))
    handle = windll.kernel32.OpenProcess(0x0410, 0, pid)
    buffer_len = c_ulong(1024)
    buffer = create_unicode_buffer(buffer_len.value)
    windll.kernel32.QueryFullProcessImageNameW(handle, 0,pointer(buffer),pointer(buffer_len))
    buffer = buffer[:]
    buffer = buffer[:buffer.index("\0")]
    return str(buffer)

def GetWindowHandle(title):
    global ghwnd, wintitle, pname
    ghwnd = None
    wintitle = title
    pname = None
    EnumWindows(WNDENUMPROC(EnumWindowsProc), 0)
    return ghwnd

def GetWindowHandleWithName(title,name):
    global ghwnd, wintitle, pname
    ghwnd = None
    wintitle = title
    pname = name
    EnumWindows(WNDENUMPROC(EnumWindowsProc), 0)
    return ghwnd

def GetWindowList():
    global windowlist
    windowlist = []
    EnumWindows(WNDENUMPROC(EnumWindowsListProc), 0)
    return windowlist

def SetForeWindow(hwnd):
    windll.user32.SetForegroundWindow(hwnd)

def SetWindowPos(hwnd,x,y,cx,cy,uflags):
    hwndinsertafter = HWND()
    windll.user32.SetWindowPos(hwnd,hwndinsertafter,x,y,cx,cy,uflags)

def GetWindowText(hwnd):
    length = windll.user32.GetWindowTextLengthW(hwnd)
    buff = create_unicode_buffer(length + 1)
    windll.user32.GetWindowTextW(hwnd, buff, length + 1)
    return buff.value

def GetWindowRect(hwnd):
    rect = RECT()
    windll.user32.GetWindowRect(hwnd, pointer(rect))
    return rect.left,rect.top,rect.right,rect.bottom