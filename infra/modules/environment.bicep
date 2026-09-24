// =============================================================================
// Container Apps Environment Module
// =============================================================================
//
// Deploys an Azure Container Apps Environment together with a Log Analytics
// workspace used for log aggregation. Optionally integrates the environment
// into a VNet (requires a dedicated /23+ subnet delegated to
// Microsoft.App/environments).
//
// =============================================================================

@description('Container Apps Environment name.')
param name string

@description('Azure region.')
param location string

@description('Log Analytics workspace name.')
param logAnalyticsWorkspaceName string = '${name}-logs'

@description('Infrastructure subnet resource ID (empty for a public environment).')
param infrastructureSubnetId string = ''

@description('Enable internal (private) load balancer for the environment.')
param internalLoadBalancer bool = false

// Log Analytics workspace used for Container Apps logs
resource logAnalyticsWorkspace 'Microsoft.OperationalInsights/workspaces@2022-10-01' = {
  name: logAnalyticsWorkspaceName
  location: location
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 30
  }
}

// Container Apps Environment
resource containerEnvironment 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: name
  location: location
  properties: union(
    {
      appLogsConfiguration: {
        destination: 'log-analytics'
        logAnalyticsConfiguration: {
          customerId: logAnalyticsWorkspace.properties.customerId
          sharedKey: logAnalyticsWorkspace.listKeys().primarySharedKey
        }
      }
    },
    !empty(infrastructureSubnetId) ? {
      vnetConfiguration: {
        infrastructureSubnetId: infrastructureSubnetId
        internal: internalLoadBalancer
      }
    } : {}
  )
}

output id string = containerEnvironment.id
output name string = containerEnvironment.name
output defaultDomain string = containerEnvironment.properties.defaultDomain
output staticIp string = containerEnvironment.properties.staticIp
output logAnalyticsWorkspaceId string = logAnalyticsWorkspace.id
