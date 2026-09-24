#!/usr/bin/env pwsh
# =============================================================================
# Register / configure the PMO Risk Recurrence Predictor app in Entra ID
# =============================================================================
#
# Provisions everything the backend + SPA need for Entra SSO and RBAC:
#   * an app registration with an SPA redirect URI (MSAL)
#   * an exposed API scope (`access_as_user`) and v2 access tokens
#     (required: the backend validates the v2 issuer and audience = client id)
#   * a `groups` claim (groupMembershipClaims=SecurityGroup) for role mapping
#   * a service principal and a client secret
#   * the three RBAC security groups, resolved (or created with -CreateGroups)
#
# USAGE
#   .\register-entra-app.ps1 -Environment dev -FrontendUrl https://app.example.com
#   .\register-entra-app.ps1 -Environment dev -FrontendUrl https://app.example.com `
#       -OutputEnv infra\deploy.dev.env -CreateGroups
#
# REQUIRED PERMISSIONS
#   Application Administrator (create app + secret). Group creation needs
#   Groups Administrator; without it, existing groups are resolved by name.
#
# =============================================================================

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('dev', 'prod')]
    [string]$Environment,

    [Parameter(Mandatory = $true)]
    [string]$FrontendUrl,

    [string]$OutputEnv = '',
    [switch]$CreateGroups,
    [string]$DisplayName = ''
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

function Write-Step { param([string]$m) Write-Host "`n==> $m" -ForegroundColor Cyan }
function Write-Ok   { param([string]$m) Write-Host "[OK] $m" -ForegroundColor Green }
function Write-Warn { param([string]$m) Write-Host "[WARN] $m" -ForegroundColor Yellow }
function Fail       { param([string]$m) Write-Host "[ERROR] $m" -ForegroundColor Red; exit 1 }

if ([string]::IsNullOrEmpty($DisplayName)) { $DisplayName = "PMO Risk Recurrence Predictor ($Environment)" }
$FrontendUrl = $FrontendUrl.TrimEnd('/')

$SystemAdminGroup    = if ($env:SYSTEM_ADMIN_GROUP)    { $env:SYSTEM_ADMIN_GROUP }    else { 'RiskApp - System Admin' }
$PmoLeadGroup        = if ($env:PMO_LEAD_GROUP)        { $env:PMO_LEAD_GROUP }        else { 'RiskApp -PMO Lead' }
$ProjectManagerGroup = if ($env:PROJECT_MANAGER_GROUP) { $env:PROJECT_MANAGER_GROUP } else { 'RiskApp - Project Manager' }

if (-not (Get-Command az -ErrorAction SilentlyContinue)) { Fail 'Azure CLI (az) not found.' }
az account show --output none 2>$null
if ($LASTEXITCODE -ne 0) { Fail "Not authenticated. Run 'az login'." }

$TenantId = az account show --query tenantId -o tsv
Write-Ok "Tenant: $TenantId"

# 1. App registration
Write-Step "Ensuring app registration: $DisplayName"
$AppId = az ad app list --display-name $DisplayName --query "[0].appId" -o tsv 2>$null
if ($AppId) {
    Write-Ok "App exists: $AppId"
}
else {
    $AppId = az ad app create --display-name $DisplayName --sign-in-audience AzureADMyOrg `
        --enable-access-token-issuance true --enable-id-token-issuance true --query appId -o tsv
    Write-Ok "App created: $AppId"
}
$ObjectId = az ad app show --id $AppId --query id -o tsv

$ScopeId = az rest --method GET --url "https://graph.microsoft.com/v1.0/applications/$ObjectId" `
    --query "api.oauth2PermissionScopes[?value=='access_as_user'].id | [0]" -o tsv 2>$null
if ([string]::IsNullOrEmpty($ScopeId) -or $ScopeId -eq 'None') { $ScopeId = [guid]::NewGuid().ToString() }

# 2. Redirect URIs, exposed scope, v2 tokens, group claims
Write-Step 'Configuring redirect URIs, exposed scope, v2 tokens and group claims...'
az ad app update --id $AppId --identifier-uris "api://$AppId" --set groupMembershipClaims=SecurityGroup --output none

$body = @{
    spa = @{ redirectUris = @($FrontendUrl, "$FrontendUrl/auth/callback") }
    api = @{
        requestedAccessTokenVersion = 2
        oauth2PermissionScopes = @(@{
            id                       = $ScopeId
            value                    = 'access_as_user'
            type                     = 'User'
            isEnabled                = $true
            adminConsentDisplayName  = 'Access PMO Risk as the signed-in user'
            adminConsentDescription  = 'Allow the SPA to call the PMO Risk API on behalf of the signed-in user.'
            userConsentDisplayName   = 'Access PMO Risk on your behalf'
            userConsentDescription   = 'Allow this app to access the PMO Risk API as you.'
        })
        preAuthorizedApplications = @(@{ appId = $AppId; delegatedPermissionIds = @($ScopeId) })
    }
    # Without requiredResourceAccess the SPA gets AADSTS650057 ("Invalid resource").
    requiredResourceAccess = @(@{ resourceAppId = $AppId; resourceAccess = @(@{ id = $ScopeId; type = 'Scope' }) })
} | ConvertTo-Json -Depth 10 -Compress

az rest --method PATCH --url "https://graph.microsoft.com/v1.0/applications/$ObjectId" `
    --headers "Content-Type=application/json" --body $body --output none
Write-Ok "Configured (spa=$FrontendUrl, scope=access_as_user, tokens=v2, claims=SecurityGroup)"

# 3. Service principal
az ad sp create --id $AppId --query id -o tsv 2>$null | Out-Null
Write-Ok 'Service principal ready'

az ad app permission grant --id $AppId --api $AppId --scope 'access_as_user' --output none 2>$null
if ($LASTEXITCODE -eq 0) { Write-Ok 'Delegated consent granted (access_as_user)' }
else { Write-Warn 'Could not pre-grant consent (pre-authorization still applies)' }

# 4. Client secret
Write-Step 'Creating client secret...'
$ClientSecret = az ad app credential reset --id $AppId --append `
    --display-name "deploy-$(Get-Date -Format 'yyyyMMddHHmm')" --query password -o tsv
if ([string]::IsNullOrEmpty($ClientSecret)) { Fail 'Could not create a client secret.' }
Write-Ok 'Client secret created'

# 5. RBAC security groups
function Resolve-Group {
    param([string]$Name)
    $id = az ad group show --group $Name --query id -o tsv 2>$null
    if ($id) { return $id }
    if ($CreateGroups) {
        $nick = ($Name.ToLower() -replace '[^a-z0-9]', '')
        $id = az ad group create --display-name $Name --mail-nickname $nick --query id -o tsv 2>$null
        if ($id) { return $id }
    }
    return ''
}

Write-Step 'Resolving RBAC security groups...'
$gSys = Resolve-Group $SystemAdminGroup
$gPmo = Resolve-Group $PmoLeadGroup
$gPm  = Resolve-Group $ProjectManagerGroup

$roleMap = [ordered]@{}
if ($gSys) { $roleMap['System Admin']    = $gSys; Write-Ok "System Admin    : $gSys" } else { Write-Warn "System Admin group '$SystemAdminGroup' not found" }
if ($gPmo) { $roleMap['PMO Lead']        = $gPmo; Write-Ok "PMO Lead        : $gPmo" } else { Write-Warn "PMO Lead group '$PmoLeadGroup' not found" }
if ($gPm)  { $roleMap['Project Manager'] = $gPm;  Write-Ok "Project Manager : $gPm" }  else { Write-Warn "Project Manager group '$ProjectManagerGroup' not found" }
$roleIds = ($roleMap | ConvertTo-Json -Compress)

# 6. Write / print
if ($OutputEnv) {
    if (-not (Test-Path $OutputEnv)) { Fail "Output env file not found: $OutputEnv" }
    Write-Step "Writing Entra keys to $OutputEnv"
    $kept = Get-Content $OutputEnv | Where-Object { $_ -notmatch '^(RISKAPP_ENTRA_|VITE_ENTRA_)' }
    $kept += "RISKAPP_ENTRA_TENANT_ID=$TenantId"
    $kept += "RISKAPP_ENTRA_CLIENT_ID=$AppId"
    $kept += "RISKAPP_ENTRA_CLIENT_SECRET=$ClientSecret"
    $kept += "RISKAPP_ENTRA_ROLE_GROUP_IDS=$roleIds"
    $kept += "VITE_ENTRA_CLIENT_ID=$AppId"
    $kept += "VITE_ENTRA_TENANT_ID=$TenantId"
    Set-Content -Path $OutputEnv -Value $kept -Encoding utf8
    Write-Ok "Updated $OutputEnv"
}

Write-Host @"

==============================================================================
ENTRA PROVISIONED
==============================================================================
App registration : $DisplayName
Client ID        : $AppId
Tenant ID        : $TenantId
Redirect URI     : $FrontendUrl
Scope            : api://$AppId/access_as_user

RISKAPP_ENTRA_TENANT_ID=$TenantId
RISKAPP_ENTRA_CLIENT_ID=$AppId
RISKAPP_ENTRA_ROLE_GROUP_IDS=$roleIds

VITE_ENTRA_CLIENT_ID=$AppId
VITE_ENTRA_TENANT_ID=$TenantId

Next: redeploy the backend (web/worker/beat) and rebuild the frontend.
"@ -ForegroundColor Green
