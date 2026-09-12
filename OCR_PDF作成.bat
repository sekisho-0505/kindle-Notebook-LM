@echo off
chcp 65001 > nul
cd /d "%~dp0"
where python > nul 2>&1
if errorlevel 1 (
  echo ERROR: Python が見つかりません。
  echo Python をインストールし、「Add python.exe to PATH」に
  echo チェックが入っていたか確認してください。
  echo.
  pause
  exit /b 1
)
echo ========================================
echo  OCR 付き PDF を作成（文字検索できる PDF）
echo ========================================
echo.
python marge_pngs.py
echo.
echo ----------------------------------------
if errorlevel 1 (
  echo [失敗] エラーで終了しました。上に出ている ERROR の行を確認してください。
) else (
  echo [成功] 正常に終了しました。
)
echo.
echo Enter キーでこの画面を閉じます。
pause > nul
