; Inno Setup script: a per-user installer for Loop Builder (no administrator rights needed).
;   iscc /DAppVersion=0.1.0 /DDistDir=..\..\dist packaging\windows\loopbuilder.iss
; Signing: CI signs Loop Builder.exe before this runs and the finished installer after (Azure Artifact Signing).
; WebView2: put MicrosoftEdgeWebview2Setup.exe (Microsoft's bootstrapper) next to this file before building;
; CI downloads it. It runs only when the Evergreen runtime isn't already installed.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef DistDir
  #define DistDir "..\..\dist"
#endif
#ifndef OutDir
  #define OutDir DistDir
#endif

[Setup]
AppId={{6C3E2B7A-4F1D-4C8E-9B2A-1D5E7F9A0C34}
AppName=Loop Builder
AppVersion={#AppVersion}
AppPublisher=Mike Huot
AppPublisherURL=https://github.com/mhuot/loop-builder
AppSupportURL=https://github.com/mhuot/loop-builder/issues
AppUpdatesURL=https://github.com/mhuot/loop-builder/releases
AppCopyright=Copyright 2026 Mike Huot
DefaultDirName={localappdata}\Programs\Loop Builder
DefaultGroupName=Loop Builder
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir={#OutDir}
OutputBaseFilename=LoopBuilder-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\Loop Builder.exe
SetupIconFile=..\icons\loop-builder.ico
MinVersion=10.0
#ifdef Sign
SignTool=signtool
SignedUninstaller=yes
#endif

[Files]
Source: "{#DistDir}\Loop Builder\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "MicrosoftEdgeWebview2Setup.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall skipifsourcedoesntexist; Check: NeedsWebView2

[Icons]
Name: "{autoprograms}\Loop Builder"; Filename: "{app}\Loop Builder.exe"
Name: "{autodesktop}\Loop Builder"; Filename: "{app}\Loop Builder.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Run]
Filename: "{tmp}\MicrosoftEdgeWebview2Setup.exe"; Parameters: "/silent /install"; StatusMsg: "Installing Microsoft Edge WebView2..."; Check: NeedsWebView2 and BootstrapperCopied; Flags: waituntilterminated
Filename: "{app}\Loop Builder.exe"; Description: "Start Loop Builder"; Flags: nowait postinstall skipifsilent

[Code]
const
  WebView2Client = '{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';

function HasWebView2At(Root: Integer; Key: String): Boolean;
var
  Version: String;
begin
  Result := RegQueryStringValue(Root, Key, 'pv', Version) and (Version <> '') and (Version <> '0.0.0.0');
end;

function BootstrapperCopied: Boolean;
begin
  Result := FileExists(ExpandConstant('{tmp}\MicrosoftEdgeWebview2Setup.exe'));
end;

{ The Evergreen runtime registers under one of these (machine-wide 64/32-bit, or per user). }
function NeedsWebView2: Boolean;
begin
  Result := not (
    HasWebView2At(HKLM, 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\' + WebView2Client) or
    HasWebView2At(HKLM, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\' + WebView2Client) or
    HasWebView2At(HKCU, 'Software\Microsoft\EdgeUpdate\Clients\' + WebView2Client));
end;
