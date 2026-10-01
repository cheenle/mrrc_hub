<#
.SYNOPSIS
  在 Windows 实例上安装 Cloud Hub 隧道（与 install_instance_tunnel.sh 对等）。

.DESCRIPTION
  <name> 与 <port> 必须与 hub 上 /etc/mrrc-hub/instances.tsv 的一行对应 —— 端口由 hub 分配，
  这一侧只是认领它。

  本脚本做四件事：
    * 用安装包**内置**的 frpc.exe 写一份 0600 等价的 frpc 配置（token 只在文件里，不进 argv）
    * 用内置的 openssl.exe 给 <name>.mrrc.vlsc.net 签一张自签证书（幂等；hub 侧按此名校验）
    * 把 MRRC_SSL_CERT / MRRC_SSL_KEY / 心跳阈值写成**用户级环境变量**，应用下次启动即生效
    * 注册一个计划任务常驻（登录时启动 + 失败自动重启），隧道因此活得比这个窗口久

  与 shell 版的差异（有意）：计划任务用 -AtLogOn 而非开机启动 —— 后者需要 SYSTEM 凭证。
  所以这台机器要保持用户登录（无人值守电台的常见做法），否则隧道会停。
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)][string]$Name,
    [Parameter(Mandatory = $true, Position = 1)][int]$Port,
    [int]$LocalPort = 8888,
    [string]$HubHost = "tunnel.mrrc.vlsc.net",
    [int]$ControlPort = 8989,
    [string]$FleetDir = "",                                 # frpc.exe / openssl.exe 所在（安装包内置）
    [string]$DataDir = (Join-Path $env:LOCALAPPDATA "MRRC\fleet"),
    [string]$CertDir = (Join-Path $env:APPDATA "MRRC-Modern\certs"),
    [switch]$Force
)

# 这里是 Continue 而不是 Stop，有一条实测理由：PowerShell 5.1 在 Stop 下会把**原生程序写 stderr**
# （openssl 的进度点 `+++…`、icacls 的正常输出）当成 terminating error，签名那一步会因此中断 ——
# 在干净 VM 上装包真跑时实测到。本脚本对每一处关键调用都显式查 $LASTEXITCODE 并用 Fail 退出，
# 所以 Continue 不会放过失败，只是不让 stderr 输出冒充失败。
$ErrorActionPreference = "Continue"

# Where this script lives. NOT as a param default: $PSScriptRoot is not reliably set while the
# param block is being bound - invoked from within another PowerShell it comes back empty, and the
# next Join-Path fails with 'parameter Path is an empty string' pointing at an innocent line.
# (Measured: cmd /c "powershell -File …" works, & powershell -File … does not.)
if (-not $FleetDir) {
    $FleetDir = $PSScriptRoot
    if (-not $FleetDir) { $FleetDir = Split-Path -Parent $MyInvocation.MyCommand.Path }
    if (-not $FleetDir) { $FleetDir = (Get-Location).Path }
}
$taskName = "MRRC Fleet Tunnel ($Name)"
$conf = Join-Path $DataDir "frpc-$Name.toml"
$fqdn = "$($Name.ToLower()).mrrc.vlsc.net"

function Fail($msg) { Write-Error $msg; exit 2 }

# ---- 令牌：只从环境变量来（不落 argv、不进历史）----
$token = $env:MRRC_HUB_TOKEN
if (-not $token) { Fail "set MRRC_HUB_TOKEN first (the frps token; read it on the hub: sudo cat /etc/frp/frps.token)" }

# ---- frpc：内置优先，其次 PATH（不外网下载：实例侧网络未必通 GitHub）----
$frpc = Join-Path $FleetDir "frpc.exe"
if (-not (Test-Path $frpc)) {
    $onPath = (Get-Command frpc.exe -ErrorAction SilentlyContinue).Source
    if ($onPath) { $frpc = $onPath; Write-Host "use frpc from PATH: $frpc" }
    else { Fail "frpc.exe not found: install package should ship it in $FleetDir (set -FleetDir if it lives elsewhere)" }
}

# ---- 证书：内置 openssl 签自签证书（hub 按 $fqdn 校验；私钥不外传）----
$openssl = Join-Path $FleetDir "openssl.exe"
$cnf  = Join-Path $FleetDir "openssl.cnf"                       # 随包带：签名不再依赖系统或编译前缀的默认配置
if (-not (Test-Path $cnf)) { Fail "missing openssl.cnf next to this script: $cnf" }
if (-not (Test-Path $openssl)) {
    $onPath = (Get-Command openssl.exe -ErrorAction SilentlyContinue).Source
    if ($onPath) { $openssl = $onPath; Write-Host "use openssl from PATH: $openssl" }
    else { Fail "openssl.exe not found: the installer ships it (needed to sign the instance certificate)" }
}
$crt = Join-Path $CertDir "fullchain.pem"
$key = Join-Path $CertDir "$($Name.ToLower()).key"
New-Item -ItemType Directory -Path $CertDir -Force | Out-Null

$needCert = $true
if ((Test-Path $crt) -and (Test-Path $key) -and (-not $Force)) {
    $subject = & $openssl x509 -in $crt -noout -subject 2>$null
    if ($subject -match [regex]::Escape("CN=$fqdn")) { $needCert = $false; Write-Host "certificate already names $fqdn, keeping it" }
}
if ($needCert) {
    & $openssl req -x509 -newkey rsa:2048 -nodes -days 3650 -keyout $key -out $crt `
        -subj "/CN=$fqdn" -addext "subjectAltName=DNS:$fqdn" `
        -addext "basicConstraints=critical,CA:FALSE" `
        -addext "keyUsage=critical,digitalSignature,keyEncipherment" `
        -addext "extendedKeyUsage=serverAuth" `
        -config $cnf 2>$null
    if ($LASTEXITCODE -ne 0) { Fail "openssl failed to sign the certificate" }
    Write-Host "signed a self-signed certificate for $fqdn (3650 days)"
}
# 私钥只给当前用户（Windows 上的 0600 等价物）
icacls $key /inheritance:r /grant:r "$($env:USERNAME):(R,W)" | Out-Null

# ---- 登记：把公钥交给 hub（私钥永不外传）----
if ($env:MRRC_ENROLL_SECRET) {
    $enrollUrl = if ($env:MRRC_ENROLL_URL) { $env:MRRC_ENROLL_URL } else { "https://portal.mrrc.vlsc.net:8899/enroll" }
    Write-Host "enrolling the certificate at $enrollUrl"
    try {
        $r = Invoke-RestMethod -Method Post -Uri $enrollUrl -TimeoutSec 30 -Body @{
            callsign = $Name
            secret   = $env:MRRC_ENROLL_SECRET
            cert     = (Get-Content $crt -Raw)
        }
        Write-Host "enrolled for: $($r.names -join ', ')"
        Write-Host "on the hub, as root: $($r.next_step)"
    } catch {
        Write-Warning "enrollment failed: $($_.Exception.Message)"
        Write-Warning "the certificate is on disk; re-run this script once the hub is reachable (idempotent)"
    }
} else {
    Write-Host "MRRC_ENROLL_SECRET not set - skipping enrollment (a self-signed certificate must be enrolled, or the entry answers 502)"
}

# ---- 应用侧设置：用户级环境变量，应用下次启动即生效 ----
[Environment]::SetEnvironmentVariable("MRRC_SSL_CERT", $crt, "User")
[Environment]::SetEnvironmentVariable("MRRC_SSL_KEY", $key, "User")
[Environment]::SetEnvironmentVariable("MRRC_REMOTE_SESSION_TX_HEARTBEAT_S", "5", "User")
Write-Host "set MRRC_SSL_CERT / MRRC_SSL_KEY / MRRC_REMOTE_SESSION_TX_HEARTBEAT_S=5 (user scope)"

# 让应用用上新环境。写用户级环境变量**不会**改变已在运行的应用的环境块（从开始菜单启动的进程
# 继承的是 Explorer 启动时的环境）：实测它因此继续用自己那张 localhost 证书，hub 侧报
# "upstream SSL certificate verify error: (18:self-signed certificate)"，入口永远 502。
$running = Get-Process -Name "MRRC-Modern-Launcher", "MRRC-Modern-Server", "scope_pipe" -ErrorAction SilentlyContinue
if ($running) {
    Write-Host "restarting the app so it picks up the certificate in its environment"
    foreach ($n in @("MRRC-Modern-Server", "scope_pipe", "MRRC-Modern-Launcher")) {
        Get-Process -Name $n -ErrorAction SilentlyContinue | ForEach-Object { $_.Kill(); Start-Sleep -Milliseconds 500 }
    }
    Start-Sleep -Seconds 2
    $launcher = Join-Path (Split-Path -Parent $FleetDir) "MRRC-Modern-Launcher.exe"
    if (Test-Path $launcher) {
        # 用带新环境的本进程去启动它，新进程就继承了证书路径（这正是从开始菜单启动做不到的）
        Start-Process -FilePath $launcher -WorkingDirectory (Split-Path -Parent $FleetDir) -WindowStyle Normal
        Write-Host "  app restarted (launcher) - it will now serve the instance certificate"
    } else {
        Write-Host "  could not find the launcher next to the fleet dir; start the app by hand so it reads the new variables"
    }
} else {
    Write-Host "the app was not running; start it now so it reads the new environment variables"
}

# ---- frpc 配置 ----
New-Item -ItemType Directory -Path $DataDir -Force | Out-Null
@"
serverAddr = "$HubHost"
serverPort = $ControlPort

auth.method = "token"
auth.token = "$token"

log.to = "$($DataDir -replace '\\', '/')/frpc-$Name.log"
log.level = "info"

[[proxies]]
name = "$Name"
type = "tcp"
localIP = "127.0.0.1"
localPort = $LocalPort
remotePort = $Port
"@ | Set-Content -Path $conf -Encoding ascii
# ASCII, not utf8: PowerShell 5.1's utf8 writes a BOM, and frpc's TOML parser rejects the file
# outright ("invalid character at start of key") - the tunnel then never starts and the entry
# answers 502 with no other error anywhere. The config is pure ASCII, so ascii is also correct.
icacls $conf /inheritance:r /grant:r "$($env:USERNAME):(R,W)" | Out-Null      # token 在文件里 ⇒ 收紧 ACL

# ---- 常驻：计划任务（登录时启动；失败自动重启）----
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
$action = New-ScheduledTaskAction -Execute $frpc -Argument "-c `"$conf`"" -WorkingDirectory $DataDir
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit (New-TimeSpan -Seconds 0)
# A local account must not be written as WORKGROUP\user - that fails with HRESULT 0x80070534
# (the account cannot be resolved). COMPUTERNAME\user is correct on workgroup and domain machines.
# Keep these comments ABOVE the statement: inside a backtick continuation they break parameter
# binding and UserId arrives empty, which is how this was diagnosed.
$principal = New-ScheduledTaskPrincipal -UserId "$env:COMPUTERNAME\$env:USERNAME" -LogonType Interactive
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal | Out-Null
# 升级应用时安装器会关掉 frpc（它住在应用目录里），而任务是登录时启动 ⇒ 不会自己回来。
# 这里在注册后总是重新启动一次：租户重跑同一条命令即可恢复隧道（脚本本来承诺幂等）。
Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
Start-ScheduledTask -TaskName $taskName
Start-Sleep -Seconds 4

Write-Host ""
Write-Host "==> $Name -> https://$fqdn`:9988 (local 127.0.0.1:$LocalPort)"
Write-Host "check:"
Write-Host "  Get-Content '$DataDir\frpc-$Name.log' -Tail 5     # want: login to server success / start proxy success"
Write-Host "  Get-ScheduledTask '$taskName' | Get-ScheduledTaskInfo"
Write-Host "  curl.exe -sk https://$fqdn`:9988/api/health        # 401 once the radio server is up"
Write-Host "  (To remove:  Stop-ScheduledTask '$taskName'; Unregister-ScheduledTask -TaskName '$taskName' -Confirm:`$false)"
