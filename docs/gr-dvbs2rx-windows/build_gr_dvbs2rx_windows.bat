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
  echo ERROR: VS Build Tools C++ workload not found at %VS_BUILDTOOLS%
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
  echo %GR_DVBS2RX_SRC% already exists, using it as-is (not re-cloning/re-patching).
)

call "%VS_BUILDTOOLS%\VC\Auxiliary\Build\vcvars64.bat"
set PATH=%RADIOCONDA%;%RADIOCONDA%\Library\bin;%RADIOCONDA%\Scripts;%PATH%

cd /d "%GR_DVBS2RX_SRC%"
if exist build rmdir /s /q build
mkdir build
cd build

"%RADIOCONDA%\Library\bin\cmake.exe" -G Ninja ^
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

"%RADIOCONDA%\Library\bin\ninja.exe"
if errorlevel 1 (
  echo BUILD FAILED
  exit /b 1
)

"%RADIOCONDA%\Library\bin\ninja.exe" install
if errorlevel 1 (
  echo INSTALL FAILED
  exit /b 1
)

echo.
echo DONE. Verify with:
echo   %RADIOCONDA%\python.exe -c "from gnuradio import dvbs2rx; print('OK')"
