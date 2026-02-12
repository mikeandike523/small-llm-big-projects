param(
    [switch]$Elevated = $false
)

# Function to check if running as admin
function Test-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

# Re-elevate if not running as admin
if (-not $Elevated -and -not (Test-Administrator)) {
    Write-Host "This script requires administrator privileges. Attempting to elevate..." -ForegroundColor Yellow
    
    try {
        $scriptPath = $MyInvocation.MyCommand.Path
        $params = "-NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`" -Elevated"
        Start-Process powershell.exe -Verb RunAs -ArgumentList $params -Wait
        exit 0
    }
    catch {
        Write-Host "ERROR: Failed to elevate script: $_" -ForegroundColor Red
        exit 1
    }
}

Write-Host "Running with administrator privileges." -ForegroundColor Green

# Get the directory containing this script
$scriptDir = Split-Path -Parent -Path $MyInvocation.MyCommand.Definition
Write-Host "Script directory: $scriptDir" -ForegroundColor Cyan

# Function to add path to environment variable
function Add-PathEnvironmentVariable {
    param(
        [string]$Path,
        [ValidateSet('User', 'System')]
        [string]$Scope = 'User'
    )
    
    try {
        # Get the appropriate registry hive
        $regPath = if ($Scope -eq 'User') {
            'HKCU:\Environment'
        }
        else {
            'HKLM:\System\CurrentControlSet\Control\Session Manager\Environment'
        }
        
        # Get current PATH value
        $currentPath = (Get-ItemProperty -Path $regPath -Name Path -ErrorAction SilentlyContinue).Path
        
        # Check if path already exists
        if ($currentPath -contains $Path -or $currentPath -split ';' -contains $Path) {
            Write-Host "$Scope PATH already contains: $Path" -ForegroundColor Gray
            return $true
        }
        
        # Add the path
        $newPath = if ($currentPath) {
            "$currentPath;$Path"
        }
        else {
            $Path
        }
        
        Set-ItemProperty -Path $regPath -Name Path -Value $newPath -Force | Out-Null
        Write-Host "Successfully added to $Scope PATH: $Path" -ForegroundColor Green
        return $true
    }
    catch {
        Write-Host "ERROR: Failed to add to $Scope PATH: $_" -ForegroundColor Red
        return $false
    }
}

# Add script directory to User PATH
$userPathSuccess = Add-PathEnvironmentVariable -Path $scriptDir -Scope 'User'

# Add script directory to System PATH
$systemPathSuccess = Add-PathEnvironmentVariable -Path $scriptDir -Scope 'System'

# Summary
Write-Host "`nInstallation Summary:" -ForegroundColor Cyan
Write-Host "====================="

if ($userPathSuccess -and $systemPathSuccess) {
    Write-Host "SUCCESS: Script directory added to both User and System PATH" -ForegroundColor Green
    Write-Host "The following directory is now in your PATH:" -ForegroundColor Green
    Write-Host "  $scriptDir" -ForegroundColor Cyan
    exit 0
}
elseif ($userPathSuccess -or $systemPathSuccess) {
    $added = @()
    if ($userPathSuccess) { $added += 'User' }
    if ($systemPathSuccess) { $added += 'System' }
    Write-Host "PARTIAL SUCCESS: Added to $($added -join ' and ') PATH only" -ForegroundColor Yellow
    exit 0
}
else {
    Write-Host "FAILURE: Could not add script directory to PATH" -ForegroundColor Red
    exit 1
}
