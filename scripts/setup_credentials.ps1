<#
.SYNOPSIS
    Store Betfair Exchange credentials as user environment variables.

.DESCRIPTION
    Prompts for each value and writes it straight to the user environment.
    Nothing is echoed to the console, written to a file in the project, or
    passed on the command line -- so the values stay out of your shell history,
    out of OneDrive, and out of any transcript.

    Run it yourself; it is interactive by design.

        powershell -ExecutionPolicy Bypass -File scripts\setup_credentials.ps1

.NOTES
    User environment variables live unencrypted in your registry hive
    (HKCU\Environment). That is local-only and never syncs, but it is not
    encrypted at rest. For a personal tool that is the usual trade-off; if you
    want better, Windows Credential Manager is the next step up.
#>

[CmdletBinding()]
param(
    [switch]$Clear
)

$ErrorActionPreference = 'Stop'

$names = @('ODDS_API_KEY', 'BETFAIR_APP_KEY', 'BETFAIR_USERNAME', 'BETFAIR_PASSWORD')

if ($Clear) {
    foreach ($n in $names) {
        [Environment]::SetEnvironmentVariable($n, $null, 'User')
        Write-Host "cleared $n"
    }
    Write-Host "`nDone. Open a new terminal for this to take effect."
    return
}

Write-Host "Odds source credentials" -ForegroundColor Cyan
Write-Host "  The Odds API key (free):  https://the-odds-api.com/"
Write-Host "  Betfair delayed app key:  https://apps.betfair.com/visualisers/api-ng-account-operations/"
Write-Host "                            (createDeveloperAppKeys, take the one labelled '-DELAY')"
Write-Host "`nThe Odds API alone is enough to run the model. The Betfair values are"
Write-Host "optional and only add an exchange cross-check -- leave them blank to skip.`n"
Write-Host "Leave any prompt blank to keep whatever is already stored.`n"

$prompts = [ordered]@{
    'ODDS_API_KEY'     = @{ Label = 'The Odds API key';                   Secret = $true }
    'BETFAIR_APP_KEY'  = @{ Label = 'Betfair delayed app key (optional)'; Secret = $true }
    'BETFAIR_USERNAME' = @{ Label = 'Betfair username (optional)';        Secret = $false }
    'BETFAIR_PASSWORD' = @{ Label = 'Betfair password (optional)';        Secret = $true }
}

foreach ($name in $prompts.Keys) {
    $spec     = $prompts[$name]
    $existing = [Environment]::GetEnvironmentVariable($name, 'User')
    $suffix   = if ($existing) { ' [currently set]' } else { '' }

    if ($spec.Secret) {
        $secure = Read-Host -Prompt "$($spec.Label)$suffix" -AsSecureString
        $bstr   = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
        try {
            $value = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
        }
        finally {
            # Wipe the unmanaged copy rather than leaving it for the GC.
            [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
        }
    }
    else {
        $value = Read-Host -Prompt "$($spec.Label)$suffix"
    }

    if ([string]::IsNullOrWhiteSpace($value)) {
        if (-not $existing) { Write-Warning "$name left unset" }
        continue
    }

    [Environment]::SetEnvironmentVariable($name, $value, 'User')
    Set-Variable -Name value -Value $null
    Write-Host "  stored $name" -ForegroundColor Green
}

Write-Host "`nStored. Open a NEW terminal, then verify with:" -ForegroundColor Cyan
Write-Host "  python scripts\discover_competitions.py"
Write-Host "`nTo remove them later: .\scripts\setup_credentials.ps1 -Clear"
