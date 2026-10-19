<#
One-time setup for GitHub Actions auto-deploy. Run it yourself in PowerShell from the project root:

    pwsh -File deploy\setup-auto-deploy.ps1 -SshAlias tencent-claude -Repo Lin-Kumiko/K-ON-office -Url https://kon.kumiko1314.cn

What it does (nothing is printed that contains the key or the server address):
  1. Generates a dedicated ed25519 key pair in a temporary folder.
  2. Installs deploy/k-on-deploy.sh on the server as /usr/local/sbin/k-on-deploy.
  3. Backs up root's authorized_keys, then adds the public key restricted by a forced command, so the key can
     only run the deploy receiver (no shell, no port forwarding, no pty).
  4. Checks the restriction works, then stores the private key, server address and host fingerprint as GitHub
     Actions secrets (DEPLOY_SSH_KEY, DEPLOY_HOST, DEPLOY_KNOWN_HOSTS) and DEPLOY_URL as a variable.
  5. Deletes the local copy of the private key.

To revoke later: remove the line ending in "github-actions-k-on-office" from /root/.ssh/authorized_keys.
#>
param(
  [Parameter(Mandatory)] [string] $SshAlias,
  [Parameter(Mandatory)] [string] $Repo,
  [Parameter(Mandatory)] [string] $Url
)
$ErrorActionPreference = 'Stop'
$comment = 'github-actions-k-on-office'
$dir = Join-Path ([IO.Path]::GetTempPath()) ("k-on-deploy-" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory $dir | Out-Null
$key = Join-Path $dir 'k-on-deploy'
try {
  Write-Host '1/5 generating deploy key'
  & ssh-keygen -q -t ed25519 -N '' -C $comment -f $key
  if (-not (Test-Path "$key.pub")) { throw 'ssh-keygen did not create the key' }
  $pub = (Get-Content "$key.pub" -Raw).Trim()

  Write-Host '2/5 installing the deploy receiver on the server'
  & scp -q -o BatchMode=yes (Join-Path $PSScriptRoot 'k-on-deploy.sh') "${SshAlias}:/root/k-on-deploy.sh.new"
  if ($LASTEXITCODE) { throw 'upload failed' }

  Write-Host '3/5 registering the key with a forced command'
  $line = "command=`"/usr/local/sbin/k-on-deploy`",no-port-forwarding,no-X11-forwarding,no-agent-forwarding,no-pty $pub"
  $remote = @"
set -e
install -o root -g root -m 755 /root/k-on-deploy.sh.new /usr/local/sbin/k-on-deploy && rm -f /root/k-on-deploy.sh.new
sed -i 's/\r`$//' /usr/local/sbin/k-on-deploy
bash -n /usr/local/sbin/k-on-deploy
TS=`$(date +%Y%m%d-%H%M%S)
cp -p /root/.ssh/authorized_keys /root/.ssh/authorized_keys.bak-`$TS
sed -i '/$comment`$/d' /root/.ssh/authorized_keys
echo '$line' >> /root/.ssh/authorized_keys
echo "authorized_keys backed up as authorized_keys.bak-`$TS"
"@
  $remote | & ssh -o BatchMode=yes $SshAlias "tr -d '\r' | bash -s"
  if ($LASTEXITCODE) { throw 'server setup failed' }

  Write-Host '4/5 checking the key can only run the receiver'
  $hostName = ((& ssh -G $SshAlias) | Where-Object { $_ -like 'hostname *' }).Split(' ')[1]
  $probe = '' | & ssh -i $key -o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes "root@$hostName" 'id' 2>&1
  if (($probe -join "`n") -notmatch 'k-on-deploy') { throw "unexpected response from the restricted key: $probe" }
  Write-Host '    ok: the key only reaches the deploy receiver (an empty bundle was rejected, nothing changed)'

  $known = (& ssh-keygen -F $hostName) | Where-Object { $_ -and -not $_.StartsWith('#') }
  if (-not $known) { throw 'server fingerprint not found in your known_hosts' }
  Get-Content $key -Raw | & gh secret set DEPLOY_SSH_KEY --repo $Repo
  $hostName | & gh secret set DEPLOY_HOST --repo $Repo
  ($known -join "`n") | & gh secret set DEPLOY_KNOWN_HOSTS --repo $Repo
  & gh variable set DEPLOY_URL --repo $Repo --body $Url
  if ($LASTEXITCODE) { throw 'setting GitHub secrets failed' }
  Write-Host '    GitHub secrets DEPLOY_SSH_KEY, DEPLOY_HOST, DEPLOY_KNOWN_HOSTS and variable DEPLOY_URL are set'
}
finally {
  Write-Host '5/5 removing the local key copy'
  Remove-Item -Recurse -Force $dir -ErrorAction SilentlyContinue
}
Write-Host 'done: every push to main now runs the tests and deploys when they pass'
