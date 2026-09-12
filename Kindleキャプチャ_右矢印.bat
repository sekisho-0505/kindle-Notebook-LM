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
echo  Kindle キャプチャ（右矢印でページ送り）
echo ========================================
echo.
echo Kindle for PC で本を開いた状態で実行してください。
echo.
python kindless.py --direction right
echo.
echo ----------------------------------------
echo 終了しました。Enter キーでこの画面を閉じます。
pause > nul
