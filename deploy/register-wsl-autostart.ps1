<#
.SYNOPSIS
    WSL上のexpense_project2バックエンドを、Windows起動時に自動起動するスケジュールタスクを登録する。

.DESCRIPTION
    WSL2はWindows起動時に自動で立ち上がらないため、タスクスケジューラから
    `wsl.exe -u idc_user -- start_backend.sh` を叩いて起動する。
    start_backend.sh 自体は冪等で、systemd ユニット(expense_project2-uvicorn.service)
    が有効ならそちらの起動を待つだけの薄いエントリポイントになっている。

.PARAMETER Distro
    起動に使うWSLディストロ名を明示指定したい場合に指定する。
    省略時は -d を付けず、Windows側の既定ディストロを使う
    (環境ごとにディストロ名が異なるため。開発環境: Ubuntu-24.04、本番PC: Ubuntu)。
#>
param(
    [string]$Distro
)

$TaskName = "WSL-expense_project2-autostart"

# wsl.exe はフルパスで指定する。PATH解決に頼ると環境によって
# 0x7E (ERROR_MOD_NOT_FOUND) で失敗することがある。
$WslExe = Join-Path $env:SystemRoot "System32\wsl.exe"
if (-not (Test-Path $WslExe)) {
    Write-Error "wsl.exe が見つかりません: $WslExe"
    exit 1
}

# 参考情報として、現在の既定ディストロ名をレジストリから取得して表示する
# (登録するタスク自体は -Distro 未指定なら -d を付けず既定ディストロに任せる)。
$LxssKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Lxss'
try {
    $defaultGuid = (Get-ItemProperty -Path $LxssKey -ErrorAction Stop).DefaultDistribution
    $defaultName = (Get-ItemProperty -Path (Join-Path $LxssKey $defaultGuid) -ErrorAction Stop).DistributionName
    Write-Host "既定のWSLディストロ: $defaultName"
} catch {
    Write-Host "既定のWSLディストロ名の取得に失敗しました（続行します）"
}

if ($Distro) {
    Write-Host "ディストロを明示指定します: $Distro"
    $WslArg = "-d $Distro -u idc_user -- /home/idc_user/expense_project2/start_backend.sh"
} else {
    Write-Host "既定のディストロを使用します（-d は付けません）"
    $WslArg = "-u idc_user -- /home/idc_user/expense_project2/start_backend.sh"
}

# 登録元シェルのカレントディレクトリ(UNCパスの場合がある)を引き継ぐと
# プロセス生成に失敗しうるため、WorkingDirectory を明示する。
$System32Dir = Join-Path $env:SystemRoot "System32"

$action = New-ScheduledTaskAction -Execute $WslExe -Argument $WslArg -WorkingDirectory $System32Dir

# 起動時トリガー: Windows起動直後に1回実行する。
$startupTrigger = New-ScheduledTaskTrigger -AtStartup

# 復旧トリガー: ログオントリガーに繰り返しを付けても次回ログオンまで発火しないため、
# 独立した -Once トリガー + -RepetitionInterval にする。WSL起動の一時的な失敗から
# 自動復旧できるよう、5分間隔で無期限に再実行を試みる。
$repeatTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes 5) `
    -RepetitionDuration (New-TimeSpan -Days 3650)

# SYSTEM ではなく idc_user で実行すること。
# WSLディストロは HKCU (ユーザーごと) に登録されるため、SYSTEM からは見えない。
# パスワードなしでバックグラウンド実行するため LogonType は S4U を使う。
$principal = New-ScheduledTaskPrincipal -UserId "idc_user" -LogonType S4U -RunLevel Highest

$noLimit = [System.TimeSpan]::Zero
$interval = New-TimeSpan -Minutes 1
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit $noLimit -RestartCount 3 -RestartInterval $interval -StartWhenAvailable

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger @($startupTrigger, $repeatTrigger) -Principal $principal -Settings $settings -Force
Write-Host "Registered: $TaskName"
