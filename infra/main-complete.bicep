// =============================================================================
// PMO Risk Recurrence Predictor — Complete Azure Infrastructure
// =============================================================================
//
// Deploys the full solution into a single resource group:
//   - User-assigned managed identity
//   - Azure Container Registry
//   - Virtual Network (optional)
//   - Azure Key Vault
//   - PostgreSQL Flexible Server + pgvector
//   - Azure Cache for Redis
//   - Blob Storage
//   - Azure OpenAI (chat + embeddings)
//   - Container Apps Environment
//   - Container Apps: web, worker, beat, frontend
//
// Secrets are wired into the Container Apps as Key Vault references resolved
// through the user-assigned managed identity, so no secret values flow through
// the deployment.
//
// =============================================================================

targetScope = 'resourceGroup'

// -----------------------------------------------------------------------------
// PARAMETERS
// -----------------------------------------------------------------------------

@description('Environment name: dev | prod')
param environmentName string

@description('Azure region for all resources')
param location string = 'eastus'

@description('Prefix for all resource names')
param prefix string = 'riskapp'

@description('Azure Container Registry name (globally unique, alphanumeric)')
param acrName string

@description('Docker image tag to deploy')
param imageTag string = 'latest'

@description('Deploy the Container Apps (false = infrastructure only)')
param deployApps bool = true

@description('Backend image name in ACR')
param backendImageName string = 'riskapp-backend'

@description('Frontend image name in ACR')
param frontendImageName string = 'riskapp-frontend'

@description('PostgreSQL admin username')
param postgresAdminUsername string = 'riskappadmin'

@description('PostgreSQL admin password')
@secure()
param postgresAdminPassword string

@description('PostgreSQL storage size in GB')
param postgresStorageGb int = 32

@description('PostgreSQL SKU name')
param postgresSkuName string = 'Standard_B2s'

@description('PostgreSQL compute tier')
@allowed([
  'Burstable'
  'GeneralPurpose'
  'MemoryOptimized'
])
param postgresTier string = 'Burstable'

@description('Redis SKU name')
@allowed([
  'Basic'
  'Standard'
  'Premium'
])
param redisSkuName string = 'Basic'

@description('Redis capacity (0 = C0 for Basic)')
param redisCapacity int = 0

@description('Key Vault name (globally unique, 3-24 chars)')
param keyVaultName string

@description('Storage account name (globally unique, lowercase alphanumeric)')
param storageAccountName string

@description('Unique suffix for globally-unique resource names')
param uniqueSuffix string = ''

@description('Use private networking (VNet + private endpoints)')
param usePrivateNetworking bool = false

@description('VNet address prefix (CIDR notation)')
param vnetAddressPrefix string = '10.0.0.0/16'

@description('PostgreSQL private-endpoint subnet prefix')
param postgresSubnetPrefix string = '10.0.1.0/24'

@description('Redis private-endpoint subnet prefix')
param redisSubnetPrefix string = '10.0.2.0/24'

@description('Container Apps infrastructure subnet prefix (must be /23 or larger)')
param containerAppsSubnetPrefix string = '10.0.4.0/23'

@description('Key Vault admin object ID for RBAC access')
param keyVaultAdminObjectId string = ''

@description('Azure OpenAI account name (auto-generated if empty)')
param openAiAccountName string = ''

@description('Deploy Azure OpenAI with model deployments')
param deployOpenAi bool = true

@description('Chat model name')
param chatModelName string = 'gpt-5.4'

@description('Chat model version')
param chatModelVersion string = '2026-03-05'

@description('Chat model deployment name')
param chatModelDeploymentName string = 'gpt-5.4'

@description('Chat deployment SKU. GPT-5.x requires GlobalStandard/DataZoneStandard.')
@allowed([
  'Standard'
  'GlobalStandard'
  'DataZoneStandard'
  'GlobalProvisionedManaged'
  'DataZoneProvisionedManaged'
])
param chatModelSkuName string = 'GlobalStandard'

@description('Chat deployment capacity (thousands of TPM)')
param chatModelCapacity int = 10

@description('Embedding model deployment name')
param embeddingModelDeploymentName string = 'text-embedding-3-small'

@description('Embedding deployment SKU')
@allowed([
  'Standard'
  'GlobalStandard'
  'DataZoneStandard'
  'GlobalProvisionedManaged'
  'DataZoneProvisionedManaged'
])
param embeddingModelSkuName string = 'GlobalStandard'

@description('Embedding deployment capacity (thousands of TPM)')
param embeddingModelCapacity int = 10

@description('Azure OpenAI REST API version used by the backend')
param azureOpenAiApiVersion string = '2025-04-01-preview'

@description('Comma-separated list of allowed CORS origins')
param corsOrigins string = '*'

// -----------------------------------------------------------------------------
// VARIABLES
// -----------------------------------------------------------------------------

var envResourceName = '${prefix}-${environmentName}-env'
var webAppName = '${prefix}-${environmentName}-web'
var workerAppName = '${prefix}-${environmentName}-worker'
var beatAppName = '${prefix}-${environmentName}-beat'
var frontendAppName = '${prefix}-${environmentName}-frontend'
var vnetName = '${prefix}-${environmentName}-vnet'
var storageContainerName = 'risk-registers'
var databaseName = 'riskapp'

var acrServer = '${acrName}.azurecr.io'
var backendImageUrl = '${acrServer}/${backendImageName}:${imageTag}'
var frontendImageUrl = '${acrServer}/${frontendImageName}:${imageTag}'

// -----------------------------------------------------------------------------
// USER-ASSIGNED MANAGED IDENTITY
// -----------------------------------------------------------------------------

resource managedIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: '${prefix}-${environmentName}-mi'
  location: location
}

var managedIdentityPrincipalId = managedIdentity.properties.principalId

// -----------------------------------------------------------------------------
// VIRTUAL NETWORK (optional)
// -----------------------------------------------------------------------------

module network './modules/network.bicep' = {
  name: 'network-deployment'
  params: {
    vnetName: vnetName
    location: location
    addressPrefix: vnetAddressPrefix
    postgresSubnetPrefix: postgresSubnetPrefix
    redisSubnetPrefix: redisSubnetPrefix
    containerAppsSubnetPrefix: containerAppsSubnetPrefix
    enablePrivateNetworking: usePrivateNetworking
  }
}

// -----------------------------------------------------------------------------
// CONTAINER REGISTRY
// -----------------------------------------------------------------------------

module acr './modules/registry.bicep' = {
  name: 'acr-deployment'
  params: {
    name: acrName
    location: location
    managedIdentityPrincipalId: managedIdentityPrincipalId
  }
}

// -----------------------------------------------------------------------------
// KEY VAULT
// -----------------------------------------------------------------------------

module keyVault './modules/keyvault.bicep' = {
  name: 'keyvault-deployment'
  params: {
    location: location
    keyVaultName: keyVaultName
    managedIdentityPrincipalId: managedIdentityPrincipalId
    adminObjectId: keyVaultAdminObjectId
    enablePurgeProtection: environmentName == 'prod'
    softDeleteRetentionInDays: 7
  }
}

var keyVaultUri = keyVault.outputs.vaultUri

// -----------------------------------------------------------------------------
// POSTGRESQL FLEXIBLE SERVER
// -----------------------------------------------------------------------------

module postgres './modules/postgres.bicep' = {
  name: 'postgres-deployment'
  params: {
    location: location
    prefix: prefix
    environmentName: environmentName
    uniqueSuffix: uniqueSuffix
    adminUsername: postgresAdminUsername
    adminPassword: postgresAdminPassword
    storageSizeGb: postgresStorageGb
    skuName: postgresSkuName
    tier: postgresTier
    databaseName: databaseName
    keyVaultName: keyVaultName
    privateEndpointSubnetId: usePrivateNetworking ? network.outputs.postgresSubnetId : ''
    vnetId: usePrivateNetworking ? network.outputs.vnetId : ''
    vnetName: usePrivateNetworking ? vnetName : ''
  }
}

// -----------------------------------------------------------------------------
// AZURE CACHE FOR REDIS
// -----------------------------------------------------------------------------

module redis './modules/redis.bicep' = {
  name: 'redis-deployment'
  params: {
    location: location
    prefix: prefix
    environmentName: environmentName
    uniqueSuffix: uniqueSuffix
    skuName: redisSkuName
    capacity: redisCapacity
    keyVaultName: keyVaultName
    privateEndpointSubnetId: usePrivateNetworking ? network.outputs.redisSubnetId : ''
    vnetId: usePrivateNetworking ? network.outputs.vnetId : ''
    vnetName: usePrivateNetworking ? vnetName : ''
  }
}

// -----------------------------------------------------------------------------
// BLOB STORAGE
// -----------------------------------------------------------------------------

module storage './modules/storage.bicep' = {
  name: 'storage-deployment'
  params: {
    storageAccountName: storageAccountName
    location: location
    containerName: storageContainerName
    managedIdentityPrincipalId: managedIdentityPrincipalId
  }
}

// -----------------------------------------------------------------------------
// AZURE OPENAI
// -----------------------------------------------------------------------------

module openAi './modules/openai.bicep' = if (deployOpenAi) {
  name: 'openai-deployment'
  params: {
    environmentName: environmentName
    location: location
    prefix: prefix
    keyVaultId: keyVault.outputs.vaultId
    uniqueSuffix: uniqueSuffix
    accountName: openAiAccountName
    chatModelName: chatModelName
    chatModelVersion: chatModelVersion
    chatModelDeploymentName: chatModelDeploymentName
    chatModelSkuName: chatModelSkuName
    chatModelCapacity: chatModelCapacity
    embeddingModelDeploymentName: embeddingModelDeploymentName
    embeddingModelSkuName: embeddingModelSkuName
    embeddingModelCapacity: embeddingModelCapacity
    managedIdentityPrincipalId: managedIdentityPrincipalId
  }
}

// -----------------------------------------------------------------------------
// CONTAINER APPS ENVIRONMENT
// -----------------------------------------------------------------------------

module containerEnvironment './modules/environment.bicep' = {
  name: 'container-environment-deployment'
  params: {
    name: envResourceName
    location: location
    infrastructureSubnetId: usePrivateNetworking ? network.outputs.containerAppsSubnetId : ''
  }
}

var containerEnvironmentId = containerEnvironment.outputs.id

// -----------------------------------------------------------------------------
// CONTAINER APPS
// -----------------------------------------------------------------------------

// Secrets are Key Vault references resolved via the managed identity, so no
// secret material passes through the deployment.
var commonSecretRefs = [
  {
    name: 'RISKAPP_DATABASE_URL'
    secretName: 'database-url'
  }
  {
    name: 'RISKAPP_REDIS_URL'
    secretName: 'redis-url'
  }
]

var commonSecrets = [
  {
    name: 'database-url'
    keyVaultUrl: '${keyVaultUri}secrets/postgresql-connection-string'
    identity: managedIdentity.id
  }
  {
    name: 'redis-url'
    keyVaultUrl: '${keyVaultUri}secrets/redis-connection-string'
    identity: managedIdentity.id
  }
]

var backendEnvVars = [
  {
    name: 'RISKAPP_ENVIRONMENT'
    value: environmentName
  }
  {
    name: 'RISKAPP_AZURE_OPENAI_ENDPOINT'
    value: deployOpenAi ? openAi.outputs.endpoint : ''
  }
  {
    name: 'RISKAPP_AZURE_OPENAI_CHAT_DEPLOYMENT'
    value: chatModelDeploymentName
  }
  {
    name: 'RISKAPP_AZURE_OPENAI_EMBEDDING_DEPLOYMENT'
    value: embeddingModelDeploymentName
  }
  {
    name: 'RISKAPP_AZURE_OPENAI_API_VERSION'
    value: azureOpenAiApiVersion
  }
  {
    name: 'RISKAPP_BLOB_ACCOUNT_NAME'
    value: storageAccountName
  }
  {
    name: 'RISKAPP_BLOB_CONTAINER'
    value: storageContainerName
  }
  {
    name: 'RISKAPP_CORS_ORIGINS'
    value: corsOrigins
  }
]

// The OpenAI API key is a Key Vault reference and only wired when deployed.
var backendSecrets = concat(
  commonSecrets,
  deployOpenAi ? [
    {
      name: 'openai-api-key'
      keyVaultUrl: '${keyVaultUri}secrets/azure-openai-api-key'
      identity: managedIdentity.id
    }
  ] : []
)

var backendSecretRefs = concat(
  commonSecretRefs,
  deployOpenAi ? [
    {
      name: 'RISKAPP_AZURE_OPENAI_API_KEY'
      secretName: 'openai-api-key'
    }
  ] : []
)

// Web App (FastAPI) — runs migrations then serves the API
module webApp './modules/container-app.bicep' = if (deployApps) {
  name: 'web-app-deployment'
  params: {
    name: webAppName
    location: location
    environmentId: containerEnvironmentId
    registryServer: acrServer
    image: backendImageUrl
    registryIdentityId: managedIdentity.id
    envVars: backendEnvVars
    secrets: backendSecrets
    secretRefs: backendSecretRefs
    command: [
      '/bin/sh'
      '-c'
      'alembic upgrade head && uvicorn riskapp.main:app --host 0.0.0.0 --port 8000'
    ]
    externalIngress: true
    targetPort: 8000
    minReplicas: 1
    maxReplicas: 2
    httpConcurrency: '80'
    managedIdentityId: managedIdentity.id
  }
}

// Worker App (Celery worker)
module workerApp './modules/container-app.bicep' = if (deployApps) {
  name: 'worker-app-deployment'
  params: {
    name: workerAppName
    location: location
    environmentId: containerEnvironmentId
    registryServer: acrServer
    image: backendImageUrl
    registryIdentityId: managedIdentity.id
    envVars: backendEnvVars
    secrets: backendSecrets
    secretRefs: backendSecretRefs
    command: [
      'celery'
      '-A'
      'riskapp.celery_app:celery_app'
      'worker'
      '--loglevel=INFO'
    ]
    externalIngress: false
    targetPort: 0
    minReplicas: 1
    maxReplicas: 2
    managedIdentityId: managedIdentity.id
  }
}

// Beat App (Celery beat scheduler)
module beatApp './modules/container-app.bicep' = if (deployApps) {
  name: 'beat-app-deployment'
  params: {
    name: beatAppName
    location: location
    environmentId: containerEnvironmentId
    registryServer: acrServer
    image: backendImageUrl
    registryIdentityId: managedIdentity.id
    envVars: backendEnvVars
    secrets: backendSecrets
    secretRefs: backendSecretRefs
    command: [
      'celery'
      '-A'
      'riskapp.celery_app:celery_app'
      'beat'
      '--loglevel=INFO'
    ]
    externalIngress: false
    targetPort: 0
    minReplicas: 1
    maxReplicas: 1
    managedIdentityId: managedIdentity.id
  }
}

// Frontend App (nginx serving the React SPA, proxying /api to the web app)
module frontendApp './modules/container-app.bicep' = if (deployApps) {
  name: 'frontend-app-deployment'
  params: {
    name: frontendAppName
    location: location
    environmentId: containerEnvironmentId
    registryServer: acrServer
    image: frontendImageUrl
    registryIdentityId: managedIdentity.id
    envVars: [
      {
        name: 'API_UPSTREAM'
        value: 'https://${webAppName}.${containerEnvironment.outputs.defaultDomain}'
      }
    ]
    secrets: []
    secretRefs: []
    command: []
    externalIngress: true
    targetPort: 80
    minReplicas: 1
    maxReplicas: 2
    httpConcurrency: '120'
    managedIdentityId: managedIdentity.id
  }
}

// -----------------------------------------------------------------------------
// OUTPUTS
// -----------------------------------------------------------------------------

output resourceGroupName string = resourceGroup().name
output managedIdentityId string = managedIdentity.id
output managedIdentityClientId string = managedIdentity.properties.clientId
output managedIdentityPrincipalId string = managedIdentityPrincipalId

output acrName string = acrName
output acrLoginServer string = acr.outputs.loginServer

output keyVaultName string = keyVault.outputs.vaultName
output keyVaultUri string = keyVaultUri

output postgresServerName string = postgres.outputs.serverName
output postgresFqdn string = postgres.outputs.fqdn
output postgresDatabaseName string = postgres.outputs.databaseName

output redisCacheName string = redis.outputs.cacheName
output redisHostname string = redis.outputs.hostname

output storageAccountName string = storage.outputs.storageAccountName
output storageContainerName string = storage.outputs.containerName

output openAiAccountName string = deployOpenAi ? openAi.outputs.accountName : ''
output openAiEndpoint string = deployOpenAi ? openAi.outputs.endpoint : ''
output openAiChatDeploymentName string = deployOpenAi ? openAi.outputs.chatDeploymentName : ''
output openAiEmbeddingDeploymentName string = deployOpenAi ? openAi.outputs.embeddingDeploymentName : ''

output containerEnvironmentId string = containerEnvironmentId
output containerEnvironmentDefaultDomain string = containerEnvironment.outputs.defaultDomain

output webAppName string = deployApps ? webAppName : ''
output webAppFqdn string = deployApps ? webApp.outputs.fqdn : ''
output frontendAppName string = deployApps ? frontendAppName : ''
output frontendAppFqdn string = deployApps ? frontendApp.outputs.fqdn : ''
output workerAppName string = deployApps ? workerAppName : ''
output beatAppName string = deployApps ? beatAppName : ''
