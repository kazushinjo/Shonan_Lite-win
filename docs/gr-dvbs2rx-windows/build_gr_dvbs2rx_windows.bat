@echo off
REM Builds and installs gr-dvbs2rx into radioconda's environment on Windows.
REM See README.md in this directory for prerequisites and background.
setlocal enabledelayedexpansion

REM ---- Adjust these if your setup differs from the defaults ----
set RADIOCONDA=%USERPROFILE%\radioconda
set GR_DVBS2RX_SRC=C:\claude\gr-dvbs2rx
set VS_BUILDTOOLS=C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools
REM ----------------------------------------------------------------

set SCRIPT_DIR=%~dp0

if not exist "%RADIOCONDA%\python.exe" (
  echo ERROR: radioconda not found at %RADIOCONDA%
  echo Install it from https://github.com/radioconda/radioconda-installer/releases first.
  exit /b 1
)

if not exist "%VS_BUILDTOOLS%\VC\Auxiliary\Build\vcvars64.bat" (
  REM ★%VS_BUILDTOOLS%は"(x86)"を含むため、%展開(ブロック解析時に丸ごと展開される)
  REM だとこのif/elseブロック全体の丸括弧の対応が崩れて後続行が構文エラーになる
  REM (実機で確認済み: "\Microsoft was unexpected at this time.")。遅延展開の
  REM !VAR!(実行時に1行ずつ展開)を使うことで回避する。
  echo ERROR: VS Build Tools C++ workload not found at !VS_BUILDTOOLS!
  echo Install "Desktop development with C++" via the Visual Studio Installer first.
  exit /b 1
)

if not exist "%GR_DVBS2RX_SRC%" (
  echo Cloning gr-dvbs2rx...
  git clone --recursive https://github.com/igorauad/gr-dvbs2rx.git "%GR_DVBS2RX_SRC%"
  if errorlevel 1 exit /b 1
  pushd "%GR_DVBS2RX_SRC%"
  git config core.autocrlf false
  git rm -r --cached . -q
  git reset --hard
  echo Applying Windows/MSVC patch...
  git apply --whitespace=nowarn "%SCRIPT_DIR%gr-dvbs2rx-windows-msvc.patch"
  if errorlevel 1 (
    echo PATCH FAILED - the patch may no longer apply cleanly to the current
    echo upstream gr-dvbs2rx master. Check git status/diff and adjust by hand.
    popd
    exit /b 1
  )
  popd
) else (
  REM Note: literal parentheses in an unquoted echo break cmd's block parser
  REM when inside an if/else block, so keep this message parenthesis-free.
  echo %GR_DVBS2RX_SRC% already exists, using it as-is - not re-cloning or re-patching.
)

call "%VS_BUILDTOOLS%\VC\Auxiliary\Build\vcvars64.bat"
REM cmake/ninja are resolved via PATH: radioconda's own copies (if `conda
REM install cmake ninja` was run there) take priority since they're
REM prepended here, but a system-wide install (e.g. via winget/pip) on the
REM tail-appended %PATH% works too - no need for both.
set PATH=%RADIOCONDA%;%RADIOCONDA%\Library\bin;%RADIOCONDA%\Scripts;%PATH%

cd /d "%GR_DVBS2RX_SRC%"
if exist build rmdir /s /q build
mkdir build
cd build

cmake -G Ninja ^
  -DCMAKE_BUILD_TYPE=Release ^
  -DCMAKE_INSTALL_PREFIX=%RADIOCONDA%\Library ^
  -DGR_PYTHON_DIR=%RADIOCONDA%\Lib\site-packages ^
  -DPYTHON_EXECUTABLE=%RADIOCONDA%\python.exe ^
  -DENABLE_DOXYGEN=OFF ^
  -DENABLE_MANPAGES=OFF ^
  -DCMAKE_POLICY_VERSION_MINIMUM=3.5 ^
  ..
if errorlevel 1 (
  echo CONFIGURE FAILED
  exit /b 1
)

cmake --build .
if errorlevel 1 (
  echo BUILD FAILED
  exit /b 1
)

cmake --install .
if errorlevel 1 (
  echo INSTALL FAILED
  exit /b 1
)

echo.
echo DONE. Verify with:
echo   %RADIOCONDA%\python.exe -c "from gnuradio import dvbs2rx; print('OK')"
