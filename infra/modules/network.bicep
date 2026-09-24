// =============================================================================
// Virtual Network Module
// =============================================================================
//
// Deploys a Virtual Network with subnets for:
//   - Azure Database for PostgreSQL  (private endpoint)
//   - Azure Cache for Redis          (private endpoint)
//   - Azure Container Apps           (VNet-integrated infrastructure subnet)
//
// NOTE: The Container Apps infrastructure subnet must be at least /23, must be
// empty and dedicated, and must be delegated to Microsoft.App/environments.
//
// =============================================================================

@description('Virtual Network name.')
param vnetName string

@description('Azure region.')
param location string

@description('VNet address prefix (CIDR notation, e.g., 10.0.0.0/16).')
param addressPrefix string = '10.0.0.0/16'

@description('PostgreSQL private-endpoint subnet prefix.')
param postgresSubnetPrefix string = '10.0.1.0/24'

@description('Redis private-endpoint subnet prefix.')
param redisSubnetPrefix string = '10.0.2.0/24'

@description('Container Apps infrastructure subnet prefix (must be /23 or larger).')
param containerAppsSubnetPrefix string = '10.0.4.0/23'

@description('Enable private networking (creates the VNet and subnets).')
param enablePrivateNetworking bool = true

var postgresSubnetName = 'postgres'
var redisSubnetName = 'redis'
var containerAppsSubnetName = 'containerapps'

// Virtual Network (only created when private networking is enabled)
resource vnet 'Microsoft.Network/virtualNetworks@2023-04-01' = if (enablePrivateNetworking) {
  name: vnetName
  location: location
  properties: {
    addressSpace: {
      addressPrefixes: [
        addressPrefix
      ]
    }
    subnets: [
      {
        name: postgresSubnetName
        properties: {
          addressPrefix: postgresSubnetPrefix
          privateEndpointNetworkPolicies: 'Enabled'
          privateLinkServiceNetworkPolicies: 'Enabled'
        }
      }
      {
        name: redisSubnetName
        properties: {
          addressPrefix: redisSubnetPrefix
          privateEndpointNetworkPolicies: 'Enabled'
          privateLinkServiceNetworkPolicies: 'Enabled'
        }
      }
      {
        name: containerAppsSubnetName
        properties: {
          addressPrefix: containerAppsSubnetPrefix
          delegations: [
            {
              name: 'containerapps-delegation'
              properties: {
                serviceName: 'Microsoft.App/environments'
              }
            }
          ]
          privateEndpointNetworkPolicies: 'Disabled'
          privateLinkServiceNetworkPolicies: 'Disabled'
        }
      }
    ]
  }
}

// Outputs are empty strings when private networking is disabled. resourceId()
// is used instead of resource-symbol access so the outputs stay valid for a
// conditionally-deployed resource.
output vnetName string = enablePrivateNetworking ? vnetName : ''
output vnetId string = enablePrivateNetworking ? resourceId('Microsoft.Network/virtualNetworks', vnetName) : ''
output postgresSubnetName string = enablePrivateNetworking ? postgresSubnetName : ''
output postgresSubnetId string = enablePrivateNetworking ? resourceId('Microsoft.Network/virtualNetworks/subnets', vnetName, postgresSubnetName) : ''
output redisSubnetName string = enablePrivateNetworking ? redisSubnetName : ''
output redisSubnetId string = enablePrivateNetworking ? resourceId('Microsoft.Network/virtualNetworks/subnets', vnetName, redisSubnetName) : ''
output containerAppsSubnetName string = enablePrivateNetworking ? containerAppsSubnetName : ''
output containerAppsSubnetId string = enablePrivateNetworking ? resourceId('Microsoft.Network/virtualNetworks/subnets', vnetName, containerAppsSubnetName) : ''
