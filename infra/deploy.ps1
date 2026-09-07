# Deploy the PMO Risk Recurrence Predictor to Azure Container Apps (Windows).
#
# PowerShell mirror of deploy.sh. Prereqs: authenticated az CLI with
# Contributor on the target subscription/RG, docker available for images.
#
#   .\infra\deploy.ps1 dev -Stage all
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet('dev', 'prod')]
    [string]$EnvironmentName,

    [ValidateSet('all', 'infra', 'images', 'apps')]
    [string]$Stage = 'all',

    [string]$ImageTag = '',
    [string]$Location = $env:AZURE_LOCATION,
    [string]$Prefix = $env:APP_PREFIX,
    [string]$AcrName = $env:ACR_NAME
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
if (-not $Location) { $Location = 'eastus' }
if (-not $Prefix) { $Prefix = 'riskapp' }

$RG = "rg-$Prefix-$EnvironmentName"
if (-not $ImageTag) { $ImageTag = 'latest' }
if (-not $AcrName) {
    $Sub = (az account show --query id -o tsv) -replace '-', ''
    $AcrName = "$Prefix$($EnvironmentName)acr$($Sub.Substring($Sub.Length - 8))"
}
$AcrServer = "$AcrName.azurecr.io"
$DeployAppend = (Get-Date -UFormat %s)

function Make-Params([string]$DeployApps) {
    $py = if (Get-Command python -ErrorAction SilentlyContinue) { 'python' } else { 'python3' }
    $out = Join-Path $env:TEMP "riskapp-params-$PID.json"
    & $py (Join-Path $PSScriptRoot 'make_params.py') `
        --environment-name $EnvironmentName `
        --prefix $Prefix `
        --location $Location `
        --acr-name $AcrName `
        --image-tag $ImageTag `
        --deploy-apps $DeployApps `
        --output $out
    return $out
}

function Invoke-Deployment([string]$DeployApps) {
    $paramsFile = Make-Params $DeployApps
    $suffix = if ($DeployApps -eq 'true') { 'apps' } else { 'infra' }
    az deployment group create `
        --resource-group $RG `
        --name "$Prefix-$EnvironmentName-$suffix-$DeployAppend" `
        --template-file (Join-Path $PSScriptRoot 'main.bicep') `
        --parameters "@$paramsFile" `
        --output none
    Remove-Item $paramsFile -ErrorAction SilentlyContinue
}

function Phase-Infra {
    Write-Host "==> [$EnvironmentName] resource group: $RG ($Location)"
    az group create --name $RG --location $Location --output none
    Write-Host "==> [$EnvironmentName] ACR: $AcrName"
    Invoke-Deployment 'false'
}

function Phase-Images {
    Write-Host "==> [$EnvironmentName] building and pushing images to $AcrServer"
    az acr login --name $AcrName
    Push-Location (Join-Path $Root 'backend')
    try {
        docker build -t "$AcrServer/riskapp-backend:$ImageTag" .
        docker push "$AcrServer/riskapp-backend:$ImageTag"
    } finally { Pop-Location }
    Push-Location (Join-Path $Root 'frontend')
    try {
        docker build `
            -t "$AcrServer/riskapp-frontend:$ImageTag" .
        docker push "$AcrServer/riskapp-frontend:$ImageTag"
    } finally { Pop-Location }
}

function Phase-Apps {
    Write-Host "==> [$EnvironmentName] deploying container apps"
    Invoke-Deployment 'true'
    $webUrl = az containerapp show -g $RG -n "$Prefix-$EnvironmentName-web" --query "properties.configuration.ingress.fqdn" -o tsv
    $frontendUrl = az containerapp show -g $RG -n "$Prefix-$EnvironmentName-frontend" --query "properties.configuration.ingress.fqdn" -o tsv
    Write-Host ""
    Write-Host "==> [$EnvironmentName] deployed"
    Write-Host "    App (SPA):    https://$frontendUrl"
    Write-Host "    API (health): https://$webUrl/health"
}

switch ($Stage) {
    'all'    { Phase-Infra; Phase-Images; Phase-Apps }
    'infra'  { Phase-Infra }
    'images' { Phase-Images }
    'apps'   { Phase-Apps }
}
