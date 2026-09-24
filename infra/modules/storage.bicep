// =============================================================================
// Azure Blob Storage Module
// =============================================================================
//
// Deploys an Azure Storage account (StorageV2, LRS) with a private container
// for risk-register uploads and grants the application's managed identity
// Storage Blob Data Contributor.
//
// Shared-key access is disabled; the application must use the managed identity.
//
// =============================================================================

@description('Storage account name (3-24 chars, lowercase alphanumeric, globally unique).')
param storageAccountName string

@description('Azure region.')
param location string

@description('Blob container name for risk register uploads.')
param containerName string = 'risk-registers'

@description('Principal ID of the managed identity that needs blob data access.')
param managedIdentityPrincipalId string = ''

// Storage Account
resource storageAccount 'Microsoft.Storage/storageAccounts@2023-01-01' = {
  name: storageAccountName
  location: location
  kind: 'StorageV2'
  sku: {
    name: 'Standard_LRS'
  }
  properties: {
    accessTier: 'Hot'
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    publicNetworkAccess: 'Enabled'
  }
}

// Blob Service
resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-01-01' = {
  name: 'default'
  parent: storageAccount
  properties: {
    deleteRetentionPolicy: {
      enabled: true
      days: 30
    }
    containerDeleteRetentionPolicy: {
      enabled: true
      days: 30
    }
  }
}

// Blob Container
resource blobContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-01-01' = {
  name: containerName
  parent: blobService
  properties: {
    publicAccess: 'None'
    metadata: {
      description: 'Risk register uploads and citation files'
    }
  }
}

// Storage Blob Data Contributor for the managed identity
resource storageBlobDataContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(managedIdentityPrincipalId)) {
  name: guid(storageAccountName, managedIdentityPrincipalId, 'storage-blob-data-contributor')
  scope: storageAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'ba92f5b4-2d11-453d-a403-e96b0029c9fe')
    principalId: managedIdentityPrincipalId
    principalType: 'ServicePrincipal'
  }
}

output storageAccountName string = storageAccount.name
output storageAccountId string = storageAccount.id
output containerName string = containerName
output blobEndpoint string = storageAccount.properties.primaryEndpoints.blob
