// =============================================================================
// Azure Key Vault Module
// =============================================================================
//
// Deploys Azure Key Vault with RBAC authorization and optional role
// assignments for a managed identity and an administrator.
//
// Role GUIDs are the real Azure built-in role definition IDs:
//   Key Vault Secrets User   : 4633458b-17de-408a-b874-0445c86b69e6
//   Key Vault Administrator  : 00482a5a-887f-4fb3-b363-3b7fe8e74483
//
// =============================================================================

@description('Azure region.')
param location string

@description('Key Vault name (must be globally unique, 3-24 chars).')
param keyVaultName string

@description('Principal ID of the managed identity that needs secret read access.')
param managedIdentityPrincipalId string = ''

@description('Object ID of the administrator user/group for full Key Vault access.')
param adminObjectId string = ''

@description('Enable purge protection (recommended for production).')
param enablePurgeProtection bool = false

@description('Soft-delete retention period in days (7-90).')
@allowed([
  7
  30
  90
])
param softDeleteRetentionInDays int = 7

var tenantId = subscription().tenantId

// Key Vault with RBAC authorization
resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: keyVaultName
  location: location
  properties: {
    sku: {
      family: 'A'
      name: 'standard'
    }
    tenantId: tenantId
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: softDeleteRetentionInDays
    enablePurgeProtection: enablePurgeProtection
    publicNetworkAccess: 'Enabled'
    networkAcls: {
      defaultAction: 'Allow'
      bypass: 'AzureServices'
    }
  }
}

// Key Vault Secrets User for the managed identity
resource keyVaultSecretsUserRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(managedIdentityPrincipalId)) {
  name: guid(keyVaultName, managedIdentityPrincipalId, 'key-vault-secrets-user')
  scope: keyVault
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '4633458b-17de-408a-b874-0445c86b69e6')
    principalId: managedIdentityPrincipalId
    principalType: 'ServicePrincipal'
  }
}

// Key Vault Administrator for the deploying administrator
resource keyVaultAdminRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(adminObjectId)) {
  name: guid(keyVaultName, adminObjectId, 'key-vault-admin')
  scope: keyVault
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '00482a5a-887f-4fb3-b363-3b7fe8e74483')
    principalId: adminObjectId
    principalType: 'User'
  }
}

output vaultName string = keyVault.name
output vaultId string = keyVault.id
output vaultUri string = keyVault.properties.vaultUri
output tenantId string = tenantId
