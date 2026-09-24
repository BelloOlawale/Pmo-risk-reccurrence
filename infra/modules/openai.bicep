// =============================================================================
// Azure OpenAI Module
// =============================================================================
//
// Deploys an Azure OpenAI (Cognitive Services) account with model deployments:
//   - Chat completions  (default: gpt-5.4, 2026-03-05)
//   - Embeddings        (default: text-embedding-3-small, 1)
//
// NOTES:
//   * Azure OpenAI is quota-controlled. Models are deployable only in regions
//     where quota has been granted for your subscription.
//   * GPT-5.x models do NOT support the legacy 'Standard' SKU. They require a
//     Global/DataZone SKU (GlobalStandard, DataZoneStandard, ...).
//     See: default chatModelSkuName below.
//   * API version 2025-06-01 is required for GPT-5.x model deployments.
//
// PARAMETERS:
//   environmentName            : Environment name (dev/prod)
//   location                   : Azure region
//   prefix                     : Resource name prefix
//   keyVaultId                 : Key Vault resource ID for storing endpoint/API key
//   uniqueSuffix               : Unique suffix for resource names
//   chatModelName              : Chat model name (e.g. gpt-5.4)
//   chatModelVersion           : Chat model version (e.g. 2026-03-05)
//   chatModelDeploymentName    : Name used when calling the deployment
//   chatModelSkuName           : SKU for the chat deployment (GlobalStandard)
//   chatModelCapacity          : Provisioned throughput (thousands of TPM)
//   embeddingModelName         : Embedding model name
//   embeddingModelVersion      : Embedding model version
//   embeddingModelDeploymentName : Name used when calling the deployment
//   embeddingModelSkuName      : SKU for the embedding deployment
//   embeddingModelCapacity     : Provisioned throughput (thousands of TPM)
//
// =============================================================================

@description('Environment name for resource naming.')
param environmentName string

@description('Azure region.')
param location string

@description('Prefix for resource names.')
param prefix string

@description('Explicit Azure OpenAI account name (auto-generated when empty).')
param accountName string = ''

@description('Key Vault resource ID for storing secrets.')
param keyVaultId string = ''

@description('Principal ID of the managed identity that needs OpenAI access.')
param managedIdentityPrincipalId string = ''

@description('Unique suffix for resource names.')
param uniqueSuffix string = ''

// ---- Chat model ------------------------------------------------------------

@description('Chat model name (must exist in the target region).')
param chatModelName string = 'gpt-5.4'

@description('Chat model version.')
param chatModelVersion string = '2026-03-05'

@description('Chat model deployment name (referenced by the application).')
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

@description('Chat deployment capacity (thousands of tokens per minute).')
param chatModelCapacity int = 10

// ---- Embedding model -------------------------------------------------------

@description('Embedding model name (must exist in the target region).')
param embeddingModelName string = 'text-embedding-3-small'

@description('Embedding model version.')
param embeddingModelVersion string = '1'

@description('Embedding model deployment name (referenced by the application).')
param embeddingModelDeploymentName string = 'text-embedding-3-small'

@description('Embedding deployment SKU.')
@allowed([
  'Standard'
  'GlobalStandard'
  'DataZoneStandard'
  'GlobalProvisionedManaged'
  'DataZoneProvisionedManaged'
])
param embeddingModelSkuName string = 'GlobalStandard'

@description('Embedding deployment capacity (thousands of tokens per minute).')
param embeddingModelCapacity int = 10

// ---- Account ---------------------------------------------------------------

@description('Azure OpenAI SKU (S0 = Standard).')
param skuName string = 'S0'

@description('Responsible AI policy name applied to model deployments.')
param raiPolicyName string = 'Microsoft.Default'

var generatedAccountName = !empty(uniqueSuffix) ? '${prefix}-${environmentName}-openai${uniqueSuffix}' : '${prefix}-${environmentName}-openai'
var openaiAccountName = !empty(accountName) ? accountName : generatedAccountName
var keyVaultName = !empty(keyVaultId) ? last(split(keyVaultId, '/')) : ''
var hasKeyVault = !empty(keyVaultId)

// Azure OpenAI Account
resource openaiAccount 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: openaiAccountName
  location: location
  kind: 'OpenAI'
  sku: {
    name: skuName
  }
  properties: {
    publicNetworkAccess: 'Enabled'
    networkAcls: {
      defaultAction: 'Allow'
    }
    customSubDomainName: openaiAccountName
  }
}

// Chat model deployment (default: gpt-5.4)
resource chatModelDeployment 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  parent: openaiAccount
  name: chatModelDeploymentName
  sku: {
    name: chatModelSkuName
    capacity: chatModelCapacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: chatModelName
      version: chatModelVersion
    }
    raiPolicyName: raiPolicyName
    versionUpgradeOption: 'NoAutoUpgrade'
  }
}

// Embedding model deployment (default: text-embedding-3-small)
resource embeddingModelDeployment 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  parent: openaiAccount
  name: embeddingModelDeploymentName
  sku: {
    name: embeddingModelSkuName
    capacity: embeddingModelCapacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: embeddingModelName
      version: embeddingModelVersion
    }
    raiPolicyName: raiPolicyName
    versionUpgradeOption: 'NoAutoUpgrade'
  }
}

// Store API key in Key Vault
resource kvApiKey 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = if (hasKeyVault) {
  name: '${keyVaultName}/azure-openai-api-key'
  properties: {
    value: openaiAccount.listKeys().key1
    contentType: 'text/plain'
  }
}

// Store endpoint in Key Vault
resource kvEndpoint 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = if (hasKeyVault) {
  name: '${keyVaultName}/azure-openai-endpoint'
  properties: {
    value: openaiAccount.properties.endpoint
    contentType: 'text/plain'
  }
}

// Store chat deployment name in Key Vault
resource kvChatDeployment 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = if (hasKeyVault) {
  name: '${keyVaultName}/azure-openai-chat-deployment'
  properties: {
    value: chatModelDeploymentName
    contentType: 'text/plain'
  }
}

// Store embedding deployment name in Key Vault
resource kvEmbeddingDeployment 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = if (hasKeyVault) {
  name: '${keyVaultName}/azure-openai-embedding-deployment'
  properties: {
    value: embeddingModelDeploymentName
    contentType: 'text/plain'
  }
}

// Cognitive Services OpenAI User for the managed identity
resource openAiUserRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(managedIdentityPrincipalId)) {
  name: guid(openaiAccountName, managedIdentityPrincipalId, 'openai-user')
  scope: openaiAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd')  // Cognitive Services OpenAI User
    principalId: managedIdentityPrincipalId
    principalType: 'ServicePrincipal'
  }
}

output accountName string = openaiAccount.name
output endpoint string = openaiAccount.properties.endpoint
output resourceId string = openaiAccount.id
output chatDeploymentName string = chatModelDeploymentName
output chatModelName string = chatModelName
output chatModelVersion string = chatModelVersion
output embeddingDeploymentName string = embeddingModelDeploymentName
output embeddingModelName string = embeddingModelName
output embeddingModelVersion string = embeddingModelVersion
