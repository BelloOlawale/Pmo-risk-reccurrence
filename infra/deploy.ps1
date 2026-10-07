#!/usr/bin/env pwsh
# =============================================================================
# PMO Risk Recurrence Predictor - Complete Azure Deployment Script (PowerShell)
# =============================================================================
#
# Deploys the whole solution to Azure. Idempotent - safe to re-run at any time
# against any Azure subscription/account with sufficient permissions.
#
# REQUIREMENTS
#   - Azure CLI (az), authenticated via `az login`
#   - Docker (for building/pushing images)
#   - Permissions: Contributor + User Access Administrator (or Owner) so that
#     role assignments and Key Vault RBAC can be created
#
# USAGE
#   .\deploy.ps1 -Environment dev
#   .\deploy.ps1 -Environment prod -Location westus2
#   .\deploy.ps1 -Environment dev -Stage infra
#   .\deploy.ps1 -Environment dev -ChatModelName gpt-5.4 -ChatModelVersion 2026-03-05
#
# STAGES
#   all     : infra -> images -> apps (default)
#   infra   : resource group + infrastructure (no container apps)
#   images  : build + push Docker images
#   apps    : (re)deploy container apps (runs the template with deployApps=true)
#
# =============================================================================

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('dev', 'prod', 'int')]
    [string]$Environment,

    [ValidateSet('all', 'infra', 'images', 'apps')]
    [string]$Stage = 'all',

    # Empty means "pick the per-environment default" (see below).
    [string]$Location = '',
    [string]$Prefix = 'riskapp',
    [string]$ImageTag = 'latest',
    [string]$AcrName = '',
    [string]$OpenAiAccountName = '',
    [string]$UniqueSuffix = '',

    [string]$ChatModelName = 'gpt-5.4',
    [string]$ChatModelVersion = '2026-03-05',
    [string]$ChatModelSku = 'GlobalStandard',
    [int]$ChatModelCapacity = 10,

    [string]$EmbeddingModelName = 'text-embedding-3-small',
    [string]$EmbeddingModelSku = 'GlobalStandard',
    [int]$EmbeddingModelCapacity = 10,

    [string]$OpenAiApiVersion = '2025-04-01-preview',
    [string]$PostgresAdminUser = 'riskappadmin',
    [int]$PostgresStorageGb = 32,
    [string]$RedisSku = 'Basic',
    [int]$RedisCapacity = 0,
    [string]$CorsOrigins = '*',

    [SecureString]$PostgresPassword,

    [switch]$UsePrivateNetworking,
    [switch]$SkipImageBuild
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

# Default region per environment when -Location is not given (int is UK South).
if ([string]::IsNullOrEmpty($Location)) {
    $Location = if ($Environment -in @('int', 'integration', 'staging')) { 'uksouth' } else { 'eastus' }
}

$ScriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot    = (Get-Item $ScriptDir).Parent.FullName
$BackendDir  = Join-Path $RepoRoot 'backend'
$FrontendDir = Join-Path $RepoRoot 'frontend'

# ---- Output helpers ---------------------------------------------------------
function Write-Step    { param([string]$m) Write-Host "`n==> $m" -ForegroundColor Cyan }
function Write-Ok      { param([string]$m) Write-Host "[OK] $m" -ForegroundColor Green }
function Write-Warn    { param([string]$m) Write-Host "[WARN] $m" -ForegroundColor Yellow }
function Fail          { param([string]$m) Write-Host "[ERROR] $m" -ForegroundColor Red; exit 1 }

Write-Host @"
=============================================================================
PMO Risk Recurrence Predictor - Azure Deployment
=============================================================================
Environment : $Environment
Stage       : $Stage
Location    : $Location
Prefix      : $Prefix
Image tag   : $ImageTag
Chat model  : $ChatModelName ($ChatModelVersion)
"@ -ForegroundColor Magenta

# =============================================================================
# PREREQUISITES
# =============================================================================

Write-Step 'Checking prerequisites...'
foreach ($tool in @('az', 'docker')) {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) { Fail "$tool is not installed or not on PATH." }
}
try { docker info 2>&1 | Out-Null } catch { Fail 'Docker is not running.' }

try { $account = az account show --output json 2>$null | ConvertFrom-Json } catch { $account = $null }
if (-not $account) { Fail "Not authenticated. Run 'az login'." }

Write-Ok "Authenticated as $($account.user.name)"
Write-Ok "Subscription: $($account.name)"
Write-Ok "Tenant: $($account.tenantId)"

az bicep install 2>&1 | Out-Null

# =============================================================================
# NAMING
# =============================================================================

if ([string]::IsNullOrEmpty($UniqueSuffix)) {
    $UniqueSuffix = ($account.id -replace '-', '').Substring($account.id.Length - 5).ToLower()
}
if ([string]::IsNullOrEmpty($AcrName))          { $AcrName = "${Prefix}${Environment}acr${UniqueSuffix}" }
if ([string]::IsNullOrEmpty($OpenAiAccountName)){ $OpenAiAccountName = "${Prefix}-${Environment}-openai${UniqueSuffix}" }

$ResourceGroup   = "rg-${Prefix}-${Environment}"
$AcrServer       = "${AcrName}.azurecr.io"
$KeyVaultName    = "${Prefix}-${Environment}-kv"
$StorageAccount  = "${Prefix}${Environment}sa${UniqueSuffix}"
$PostgresServer  = "${Prefix}-${Environment}-postgres${UniqueSuffix}"
$RedisCache      = "${Prefix}-${Environment}-redis${UniqueSuffix}"
$WebApp          = "${Prefix}-${Environment}-web"
$FrontendApp     = "${Prefix}-${Environment}-frontend"
$BackendImage    = 'riskapp-backend'
$FrontendImage   = 'riskapp-frontend'

if ($null -eq $PostgresPassword) {
    $PostgresPassword = Read-Host -AsSecureString 'Enter PostgreSQL admin password (min 8 chars)'
}
$PostgresPlain = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto(
    [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($PostgresPassword))
if ($PostgresPlain.Length -lt 8) { Fail 'PostgreSQL password must be at least 8 characters.' }

# =============================================================================
# BICEP DEPLOYMENT (shared by infra and apps stages)
# =============================================================================

function Invoke-BicepDeployment {
    param([bool]$DeployApps)

    if ($DeployApps) { $kind = 'apps' } else { $kind = 'infra' }
    $deploymentName = "${Prefix}-${Environment}-${kind}-$(Get-Date -Format 'yyyyMMddHHmmss')"
    $currentUser = (az ad signed-in-user show --query id -o tsv 2>$null)

    $params = @{
        environmentName           = @{ value = $Environment }
        location                  = @{ value = $Location }
        prefix                    = @{ value = $Prefix }
        acrName                   = @{ value = $AcrName }
        imageTag                  = @{ value = $ImageTag }
        backendImageName          = @{ value = $BackendImage }
        frontendImageName         = @{ value = $FrontendImage }
        deployApps                = @{ value = $DeployApps }
        postgresAdminUsername     = @{ value = $PostgresAdminUser }
        postgresAdminPassword     = @{ value = $PostgresPlain }
        postgresStorageGb         = @{ value = $PostgresStorageGb }
        redisSkuName              = @{ value = $RedisSku }
        redisCapacity             = @{ value = $RedisCapacity }
        keyVaultName              = @{ value = $KeyVaultName }
        storageAccountName        = @{ value = $StorageAccount }
        uniqueSuffix              = @{ value = $UniqueSuffix }
        usePrivateNetworking      = @{ value = [bool]$UsePrivateNetworking }
        keyVaultAdminObjectId     = @{ value = $currentUser }
        openAiAccountName         = @{ value = $OpenAiAccountName }
        chatModelName             = @{ value = $ChatModelName }
        chatModelVersion          = @{ value = $ChatModelVersion }
        chatModelDeploymentName   = @{ value = $ChatModelName }
        chatModelSkuName          = @{ value = $ChatModelSku }
        chatModelCapacity         = @{ value = $ChatModelCapacity }
        embeddingModelDeploymentName = @{ value = $EmbeddingModelName }
        embeddingModelSkuName     = @{ value = $EmbeddingModelSku }
        embeddingModelCapacity    = @{ value = $EmbeddingModelCapacity }
        azureOpenAiApiVersion     = @{ value = $OpenAiApiVersion }
        corsOrigins               = @{ value = $CorsOrigins }
    }

    $paramsFile = New-TemporaryFile
    try {
        @{ '$schema' = 'https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#'
           contentVersion = '1.0.0.0'; parameters = $params } |
            ConvertTo-Json -Depth 10 | Set-Content -Path $paramsFile.FullName -Encoding utf8

        Write-Step "Deploying template (deployApps=$DeployApps) as '$deploymentName'..."
        az deployment group create `
            --resource-group $ResourceGroup `
            --name $deploymentName `
            --template-file (Join-Path $ScriptDir 'main-complete.bicep') `
            --parameters "@$($paramsFile.FullName)" `
            --output none
        if ($LASTEXITCODE -ne 0) {
            Fail "Bicep deployment failed. Inspect: az deployment group show -g $ResourceGroup -n $deploymentName"
        }
        Write-Ok "Template deployed (deployApps=$DeployApps)"
    }
    finally {
        Remove-Item $paramsFile.FullName -Force -ErrorAction SilentlyContinue
    }
}

# =============================================================================
# STAGE: INFRA
# =============================================================================

if ($Stage -eq 'all' -or $Stage -eq 'infra') {
    Write-Step "Ensuring resource group '$ResourceGroup' in $Location..."
    az group show --name $ResourceGroup --output none 2>$null
    if ($LASTEXITCODE -ne 0) {
        az group create --name $ResourceGroup --location $Location --output none
        Write-Ok "Resource group created: $ResourceGroup"
    } else {
        Write-Ok "Resource group exists: $ResourceGroup"
    }
    Invoke-BicepDeployment -DeployApps $false
}

# =============================================================================
# STAGE: IMAGES
# =============================================================================

if (-not $SkipImageBuild -and ($Stage -eq 'all' -or $Stage -eq 'images')) {
    Write-Step "Building and pushing images to $AcrServer..."
    az acr login --name $AcrName 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) { Fail 'az acr login failed' }

    Write-Step 'Building backend image...'
    docker build -t "${AcrServer}/${BackendImage}:${ImageTag}" $BackendDir
    if ($LASTEXITCODE -ne 0) { Fail 'Backend build failed' }
    docker push "${AcrServer}/${BackendImage}:${ImageTag}"
    if ($LASTEXITCODE -ne 0) { Fail 'Backend push failed' }

    Write-Step 'Building frontend image...'
    $buildArgs = @()
    $authMode = if ($env:VITE_AUTH_MODE) { $env:VITE_AUTH_MODE } else { 'password' }
    $buildArgs += '--build-arg', "VITE_AUTH_MODE=$authMode"
    docker build @buildArgs -t "${AcrServer}/${FrontendImage}:${ImageTag}" $FrontendDir
    if ($LASTEXITCODE -ne 0) { Fail 'Frontend build failed' }
    docker push "${AcrServer}/${FrontendImage}:${ImageTag}"
    if ($LASTEXITCODE -ne 0) { Fail 'Frontend push failed' }

    Write-Ok "Pushed backend and frontend images (${ImageTag})"
}

# =============================================================================
# STAGE: APPS
# =============================================================================

if ($Stage -eq 'all' -or $Stage -eq 'apps') {
    Invoke-BicepDeployment -DeployApps $true
}

# =============================================================================
# ENTRA ID APP REGISTRATION
# =============================================================================

Write-Step 'Checking Entra ID app registration...'
$entraAppName = "PMO Risk Recurrence Predictor (${Environment})"
$entraTenantId = $account.tenantId
$entraClientId = ''
$entraCallback = ''

$existing = @(az ad app list --display-name $entraAppName --output json 2>$null | ConvertFrom-Json)
if ($existing.Count -gt 0 -and $existing[0]) {
    $entraClientId = $existing[0].appId
    Write-Ok "Entra app already exists: $entraClientId"
}
else {
    $frontendUrl = az containerapp show -g $ResourceGroup -n $FrontendApp `
        --query 'properties.configuration.ingress.fqdn' -o tsv 2>$null
    if ($frontendUrl) { $entraCallback = "https://$frontendUrl" } else { $entraCallback = 'http://localhost:5173' }

    Write-Step 'Creating Entra app registration...'
    $newApp = az ad app create `
        --display-name $entraAppName `
        --web-redirect-uris $entraCallback `
        --enable-access-token-issuance true `
        --enable-id-token-issuance true `
        --sign-audience AzureADMyOrg `
        --output json 2>$null | ConvertFrom-Json
    if ($newApp) {
        $entraClientId = $newApp.appId
        Write-Ok "Entra app created: $entraClientId"

        $secretJson = az ad app credential reset --id $entraClientId --append --output json 2>$null | ConvertFrom-Json
        if ($secretJson) {
            az keyvault secret set --vault-name $KeyVaultName --name 'entra-client-secret' --value $secretJson.password --output none
            if ($LASTEXITCODE -eq 0) { Write-Ok 'Client secret stored in Key Vault' }
            else { Write-Warn 'Could not store client secret in Key Vault' }
        }
    }
    else {
        Write-Warn 'Could not create Entra app registration (needs Application Administrator)'
    }
}

if ($entraClientId) {
    az keyvault secret set --vault-name $KeyVaultName --name 'entra-client-id' --value $entraClientId --output none 2>$null
    az keyvault secret set --vault-name $KeyVaultName --name 'entra-tenant-id' --value $entraTenantId --output none 2>$null
    Write-Ok 'Entra configuration stored in Key Vault'
}

# =============================================================================
# SUMMARY
# =============================================================================

$webFqdn = az containerapp show -g $ResourceGroup -n $WebApp `
    --query 'properties.configuration.ingress.fqdn' -o tsv 2>$null
$frontendFqdn = az containerapp show -g $ResourceGroup -n $FrontendApp `
    --query 'properties.configuration.ingress.fqdn' -o tsv 2>$null
$openAiEndpoint = az cognitiveservices account show -g $ResourceGroup -n $OpenAiAccountName `
    --query 'properties.endpoint' -o tsv 2>$null

Write-Host @"

=============================================================================
DEPLOYMENT COMPLETE
=============================================================================
Resource group : $ResourceGroup
Location       : $Location

Endpoints
---------
Frontend       : $(if ($frontendFqdn) { "https://$frontendFqdn" })
API health     : $(if ($webFqdn) { "https://$webFqdn/health" })
API docs       : $(if ($webFqdn) { "https://$webFqdn/docs" })

Azure resources
---------------
Container Registry : $AcrServer
Key Vault          : $KeyVaultName
PostgreSQL         : $PostgresServer
Redis              : $RedisCache
Storage account    : $StorageAccount
Azure OpenAI       : $OpenAiAccountName

Models
------
Chat               : $ChatModelName ($ChatModelVersion, $ChatModelSku)
Embeddings         : $EmbeddingModelName ($EmbeddingModelSku)
Endpoint           : $openAiEndpoint

Entra ID
--------
App registration   : $entraAppName
Client ID          : $(if ($entraClientId) { $entraClientId } else { '<not created>' })
Tenant ID          : $entraTenantId

Images
------
Backend            : ${AcrServer}/${BackendImage}:${ImageTag}
Frontend           : ${AcrServer}/${FrontendImage}:${ImageTag}

Next steps
----------
1. Create Entra security groups and store their IDs in the 'entra-role-group-ids' secret.
2. Set remaining secrets (ACS, blob) - see infra/README.md.
3. If the frontend was built before the Entra app existed, rebuild it with
   VITE_AUTH_MODE=password (default) and re-run -Stage images.
"@ -ForegroundColor Green

if ($frontendFqdn) { $frontendUrlOut = "https://$frontendFqdn" } else { $frontendUrlOut = '' }
if ($webFqdn) { $apiUrlOut = "https://$webFqdn" } else { $apiUrlOut = '' }

$info = [ordered]@{
    resourceGroup        = $ResourceGroup
    location             = $Location
    environment          = $Environment
    frontendUrl          = $frontendUrlOut
    apiUrl               = $apiUrlOut
    acrServer            = $AcrServer
    keyVaultName         = $KeyVaultName
    openAiAccountName    = $OpenAiAccountName
    openAiEndpoint       = $openAiEndpoint
    openAiChatModel      = $ChatModelName
    openAiChatModelVersion = $ChatModelVersion
    openAiEmbeddingModel = $EmbeddingModelName
    entraClientId        = $entraClientId
    entraTenantId        = $entraTenantId
    deploymentDate       = (Get-Date).ToString('o')
}
$infoFile = Join-Path $ScriptDir "deployment-info-${Environment}.json"
$info | ConvertTo-Json | Set-Content -Path $infoFile -Encoding utf8
Write-Ok "Deployment info written to $infoFile"
