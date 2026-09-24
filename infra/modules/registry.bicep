// =============================================================================
// Azure Container Registry Module
// =============================================================================
//
// Deploys an Azure Container Registry and grants the application's managed
// identity AcrPull so Container Apps can pull images without stored
// credentials.
//
// =============================================================================

@description('Container Registry name (5-50 chars, alphanumeric only, globally unique).')
param name string

@description('Azure region.')
param location string

@description('Principal ID of the managed identity that needs image pull access.')
param managedIdentityPrincipalId string = ''

@description('Container Registry SKU.')
@allowed([
  'Basic'
  'Standard'
  'Premium'
])
param skuName string = 'Basic'

@description('Enable the registry admin account (used by CI/CD push pipelines).')
param adminUserEnabled bool = true

// Container Registry
resource containerRegistry 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: name
  location: location
  sku: {
    name: skuName
  }
  properties: union(
    {
      adminUserEnabled: adminUserEnabled
      publicNetworkAccess: 'Enabled'
      policies: {
        quarantinePolicy: {
          status: 'disabled'
        }
        trustPolicy: {
          type: 'Notary'
          status: 'disabled'
        }
        retentionPolicy: {
          days: 7
          status: 'disabled'
        }
      }
    },
    // Network rule sets are only supported on the Premium SKU. Setting the
    // property at all on Basic/Standard fails with NetworkRuleNotSupported.
    skuName == 'Premium' ? {
      networkRuleSet: {
        defaultAction: 'Allow'
      }
    } : {}
  )
}

// AcrPull for the managed identity
resource acrPullRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(managedIdentityPrincipalId)) {
  name: guid(name, managedIdentityPrincipalId, 'acr-pull')
  scope: containerRegistry
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '7f951dda-4ed3-4680-a7ca-43fe172d538d')
    principalId: managedIdentityPrincipalId
    principalType: 'ServicePrincipal'
  }
}

output loginServer string = containerRegistry.properties.loginServer
output acrId string = containerRegistry.id
output name string = containerRegistry.name
