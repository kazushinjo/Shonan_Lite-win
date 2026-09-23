; Shonan_Lite for Windows - フルパッケージインストーラ
; PyQt5 GUI本体(PyInstallerでビルド済み) + ffmpeg + radioconda(GNU Radio/gr-iio) +
; 事前ビルド済みgr-dvbs2rxバイナリを1本のインストーラにまとめる。
;
; ビルド方法: build_installer/README.md を参照。以下の手順は
; build_installer/build_installer.ps1 で自動化してある。手動で行う場合の前提:
;   1. build_installer/dist/ShonanLite/ が存在すること(PyInstallerでビルド済み)
;   2. build_installer/staging/{ffmpeg,radioconda,dvbs2rx_pyd,dvbs2rx_dll}/ が
;      存在すること(準備方法はbuild_installer/README.mdの「stagingの中身」参照)
;   3. "C:\Users\<user>\AppData\Local\Programs\Inno Setup 6\ISCC.exe" ShonanLiteSetup.iss
;
; MyAppVersionはアプリ本体のバージョン(app/gui/manual_content_win.pyのMANUAL_VERSION)と
; 揃えること。

#define MyAppName "Shonan_Lite for Windows"
#define MyAppVersion "1.1.4"
#define MyAppPublisher "Kazuichi Shinjo"
#define MyAppURL "https://github.com/kazushinjo/Shonan_Lite-win"
#define MyAppExeName "ShonanLite.exe"
; このインストーラがradiocondaを導入したことを示す印ファイル({app}直下)。
; アンインストール時にradiocondaも削除してよいかの判定に使う。
#define RadicondaMarkerName "radioconda_installed_by_shonan.txt"

[Setup]
; ★このGUIDはこのアプリ専用。将来のバージョンでも変更しないこと
; (変更すると「別アプリ」としてインストールされ、アップグレードにならない)。
AppId={{7B2A5C6E-6C7A-4B3E-9E7D-3B5B7A9C2E11}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
DefaultDirName={autopf}\Shonan_Lite
DefaultGroupName=Shonan_Lite for Windows
DisableProgramGroupPage=yes
OutputDir=output
; インストール開始前に使用許諾・免責事項を表示し、同意を求める(サイレントインストールでは表示されない)。
LicenseFile=license_and_disclaimer.txt
OutputBaseFilename=ShonanLiteSetup
SetupIconFile=..\windows\shonan_lite_icon.ico
Compression=lzma2/ultra
SolidCompression=yes
WizardStyle=modern
; radioconda・ffmpegを含めるためインストーラ自体が1GB近くなる。
; 32bit環境は対象外(radioconda/ffmpegともにx64のみ提供)。
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest

[Languages]
Name: "japanese"; MessagesFile: "compiler:Languages\Japanese.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
; PyInstallerでビルド済みのGUI本体一式(ShonanLite.exe + _internal\)
Source: "dist\ShonanLite\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

; ライセンス全文(GPLv3)。インストール先に LICENSE.txt として置く。
Source: "..\LICENSE"; DestDir: "{app}"; DestName: "LICENSE.txt"; Flags: ignoreversion

; ffmpeg(映像/音声入出力用。システムPATHは変更せず{app}\ffmpeg\に同梱し、
; アプリ起動時にプロセス内PATHへ追加する。platform_compat.pyの
; _add_bundled_ffmpeg_to_path()参照)。
Source: "staging\ffmpeg\ffmpeg.exe"; DestDir: "{app}\ffmpeg"; Flags: ignoreversion

; radioconda(GNU Radio + gr-iio、受信復調用)。インストーラ本体には同梱するが
; インストール先はProgram Filesではなく%USERPROFILE%\radioconda
; (platform_compat.gnuradio_python_executable()の既定探索パスに合わせる)。
; 既にradioconda導入済みの場合は再インストールしない(RadicondaMissingで判定)。
Source: "staging\radioconda\radioconda-installer.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall

; 事前ビルド済みgr-dvbs2rx(radioconda 2025.03.14 / GNU Radio 3.10.12.0 /
; Python 3.12.9でビルド。docs/gr-dvbs2rx-windows/README.md参照)。
; radioconda-installer実行後、[Code]のCurStepChangedでradioconda環境内へコピーする。
Source: "staging\dvbs2rx_pyd\gnuradio\dvbs2rx\*"; DestDir: "{app}\_dvbs2rx_prebuilt\site-packages\gnuradio\dvbs2rx"; Flags: ignoreversion
Source: "staging\dvbs2rx_dll\gnuradio-dvbs2rx.dll"; DestDir: "{app}\_dvbs2rx_prebuilt\bin"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Run]
; radioconda本体のサイレントインストール(既存導入済みならスキップ)。
; /InstallationType=JustMe /RegisterPython=0: このユーザーのみ・システムのpython登録なし。
; 600MB近いインストーラの展開・コピーのため数分かかる(StatusMsgで案内)。
Filename: "{tmp}\radioconda-installer.exe"; \
    Parameters: "/InstallationType=JustMe /RegisterPython=0 /AddToPath=0 /S /D={code:GetRadicondaDir}"; \
    StatusMsg: "GNU Radio 実行環境(radioconda)をインストールしています... (数分かかります)"; \
    Check: RadicondaMissing; Flags: waituntilterminated

Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; このインストーラがradiocondaを導入した印(CurStepChangedで作成)。
Type: files; Name: "{app}\{#RadicondaMarkerName}"

[Code]
var
  // インストール開始時点でradiocondaが未導入だったか。導入済みの環境(他のGNU Radio
  // 系ソフトが使っている可能性がある)を、アンインストール時に消さないための判定に使う。
  RadicondaWasMissing: Boolean;

function GetRadicondaDir(Param: string): string;
begin
  Result := ExpandConstant('{%USERPROFILE}') + '\radioconda';
end;

function RadicondaMissing(): Boolean;
begin
  Result := not FileExists(GetRadicondaDir('') + '\python.exe');
end;

function GetRadicondaMarkerPath(): string;
begin
  Result := ExpandConstant('{app}\{#RadicondaMarkerName}');
end;

function InitializeSetup(): Boolean;
begin
  RadicondaWasMissing := RadicondaMissing();
  Result := True;
end;

// radioconda-installer([Run]で実行済み)の直下に、事前ビルド済みgr-dvbs2rx一式を
// コピーする。gr-dvbs2rx自体はconda-forgeに存在しないため、radioconda本体には
// 含まれない(docs/gr-dvbs2rx-windows/README.md参照)。バージョンが完全一致
// しないradioconda環境にコピーするとImportError/クラッシュの恐れがあるため、
// 導入時に一致確認は行わずそのままコピーする(README記載のバージョンでのみ動作保証)。
procedure CopyPrebuiltDvbs2rx();
var
  RadicondaDir, SrcDir, DestDir: string;
begin
  RadicondaDir := GetRadicondaDir('');
  // ★フォルダの有無ではなくpython.exeの有無で判定する。radioconda-installerが
  // 失敗しても[Run]は終了コードを見ずに進むため、Lib\だけが残ったフォルダへ
  // gr-dvbs2rxをコピーして「導入済み」に見えるだけの状態になっていた(実機で確認)。
  if not FileExists(RadicondaDir + '\python.exe') then
  begin
    Log('radioconda is not installed at ' + RadicondaDir + '; skipping gr-dvbs2rx copy');
    SuppressibleMsgBox(
      'GNU Radio 実行環境(radioconda)を ' + RadicondaDir + ' に導入できませんでした。' + #13#10 +
      'このままでは受信(RX)が動作しません。' + #13#10#13#10 +
      RadicondaDir + ' フォルダが残っている場合は削除してから、' +
      'このインストーラをもう一度実行してください。',
      mbError, MB_OK, IDOK);
    exit;
  end;

  SrcDir := ExpandConstant('{app}\_dvbs2rx_prebuilt\site-packages\gnuradio\dvbs2rx');
  DestDir := RadicondaDir + '\Lib\site-packages\gnuradio\dvbs2rx';
  ForceDirectories(DestDir);
  CopyFile(SrcDir + '\__init__.py', DestDir + '\__init__.py', False);
  CopyFile(SrcDir + '\defs.py', DestDir + '\defs.py', False);
  CopyFile(SrcDir + '\params.py', DestDir + '\params.py', False);
  CopyFile(SrcDir + '\utils.py', DestDir + '\utils.py', False);
  CopyFile(SrcDir + '\dvbs2rx_python.cp312-win_amd64.pyd', DestDir + '\dvbs2rx_python.cp312-win_amd64.pyd', False);

  SrcDir := ExpandConstant('{app}\_dvbs2rx_prebuilt\bin');
  DestDir := RadicondaDir + '\Library\bin';
  CopyFile(SrcDir + '\gnuradio-dvbs2rx.dll', DestDir + '\gnuradio-dvbs2rx.dll', False);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    CopyPrebuiltDvbs2rx();
    // このインストーラがradiocondaを導入した場合だけ印を残す。上書きインストール
    // (RadicondaWasMissing=False)では印を作り直さず、以前の印はそのまま残る。
    if RadicondaWasMissing and FileExists(GetRadicondaDir('') + '\python.exe') then
      SaveStringToFile(GetRadicondaMarkerPath(), GetRadicondaDir(''), False);
  end;
end;

// アンインストール時、このインストーラが導入したradiocondaだけを削除する。
// 印がない(=既存のradiocondaを使っていた、または旧版で導入した)場合は何もしない。
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  RadicondaDir: string;
begin
  if CurUninstallStep <> usUninstall then
    exit;
  if not FileExists(GetRadicondaMarkerPath()) then
    exit;
  RadicondaDir := GetRadicondaDir('');
  if not DirExists(RadicondaDir) then
    exit;
  if SuppressibleMsgBox(
       'このアプリと一緒に導入したGNU Radio実行環境(radioconda)も削除しますか?' + #13#10#13#10 +
       RadicondaDir + #13#10#13#10 +
       '他のソフトでこのフォルダを使っている場合は「いいえ」を選んでください。',
       mbConfirmation, MB_YESNO, IDYES) = IDYES then
  begin
    if DelTree(RadicondaDir, True, True, True) then
      Log('radioconda removed: ' + RadicondaDir)
    else
      SuppressibleMsgBox(
        RadicondaDir + ' を完全には削除できませんでした。' + #13#10 +
        '使用中のプログラムを終了してから、フォルダを手動で削除してください。',
        mbError, MB_OK, IDOK);
  end;
end;
