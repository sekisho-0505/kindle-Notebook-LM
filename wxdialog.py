import wx
from enum import Enum

app = wx.App()
class Icon(Enum):
    Information = wx.ICON_INFORMATION
    Question = wx.ICON_QUESTION
    Exclamation = wx.ICON_EXCLAMATION
    Warning = wx.ICON_EXCLAMATION
    Error = wx.ICON_ERROR

class SimpleDialog:
    @staticmethod
    def askstring(title="", label="",value= "" ,parent=None, width=0, height=0)-> tuple[bool, str]:
        dlg = wx.TextEntryDialog(None, label,caption = title,value = value)
        dlg.Size = (width, height)
        dlg.WindowStyle |= wx.STAY_ON_TOP
        r = dlg.ShowModal() == wx.ID_OK
        v = dlg.GetValue()
        dlg.Destroy()
        return r, v
    
    @staticmethod
    def ask(parent = None, title="", label="", icon=Icon.Information)-> bool:
        dlg = wx.MessageDialog(None, label, title, wx.OK | wx.CANCEL | icon.value)
        dlg.WindowStyle |= wx.STAY_ON_TOP
        r = dlg.ShowModal() == wx.ID_OK
        dlg.Destroy()
        return r

    @staticmethod
    def infomation(parent = None, title="", label="", icon=Icon.Information)-> bool:
        dlg = wx.MessageDialog(None, label, title, wx.OK | icon.value)
        dlg.WindowStyle |= wx.STAY_ON_TOP
        dlg.ShowModal()
        dlg.Destroy()
        return True