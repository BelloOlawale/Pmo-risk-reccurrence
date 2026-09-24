// =============================================================================
// Azure Cache for Redis Module
// =============================================================================
//
// Deploys Azure Cache for Redis (Basic / Standard / Premium) used as the
// Celery broker and result backend. Optionally exposes it over a private
// endpoint with a private DNS zone.
//
// NOTE: Only the classic `Microsoft.Cache/redis` tiers are supported here.
// They are the tiers addressable by `az redis list-keys`, which the deployment
// scripts rely on.
//
// =============================================================================

@description('Azure region.')
param location string

@description('Resource name prefix.')
param prefix string

@description('Environment name (dev/prod).')
param environmentName string

@description('Unique suffix appended to globally-unique names.')
param uniqueSuffix string = ''

@description('Azure Cache for Redis SKU.')
@allowed([
  'Basic'
  'Standard'
  'Premium'
])
param skuName string = 'Basic'

@description('Cache size. Basic: 0=C0,1=C1.. Standard: 1=C1.. Premium: 1=P1..')
param capacity int = 0

@description('Key Vault name used to store connection secrets (empty to skip).')
param keyVaultName string = ''

@description('Private endpoint subnet resource ID (empty for public access).')
param privateEndpointSubnetId string = ''

@description('Virtual Network resource ID (required when using a private endpoint).')
param vnetId string = ''

@description('Virtual Network name (required when using a private endpoint).')
param vnetName string = ''

var cacheName = !empty(uniqueSuffix) ? '${prefix}-${environmentName}-redis${uniqueSuffix}' : '${prefix}-${environmentName}-redis'
var hostName = '${cacheName}.redis.cache.windows.net'
var sslPort = 6380
var usePrivateEndpoint = !empty(privateEndpointSubnetId)
var hasKeyVault = !empty(keyVaultName)
var skuFamily = skuName == 'Premium' ? 'P' : 'C'

// Azure Cache for Redis
resource redisCache 'Microsoft.Cache/redis@2023-08-01' = {
  name: cacheName
  location: location
  properties: {
    sku: {
      name: skuName
      family: skuFamily
      capacity: capacity
    }
    enableNonSslPort: false
    minimumTlsVersion: 'Tls1_2'
  }
}

// --- Private networking -----------------------------------------------------

resource privateDnsZone 'Microsoft.Network/privateDnsZones@2020-06-01' = if (usePrivateEndpoint) {
  name: 'privatelink.redis.cache.windows.net'
  location: 'global'
}

resource privateDnsZoneLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2020-06-01' = if (usePrivateEndpoint) {
  parent: privateDnsZone
  name: '${vnetName}-link'
  location: 'global'
  properties: {
    registrationEnabled: false
    virtualNetwork: {
      id: vnetId
    }
  }
}

resource privateEndpoint 'Microsoft.Network/privateEndpoints@2023-04-01' = if (usePrivateEndpoint) {
  name: '${cacheName}-pe'
  location: location
  properties: {
    subnet: {
      id: privateEndpointSubnetId
    }
    privateLinkServiceConnections: [
      {
        name: '${cacheName}-pls'
        properties: {
          privateLinkServiceId: redisCache.id
          groupIds: [
            'redisCache'
          ]
        }
      }
    ]
  }
}

resource privateEndpointDnsGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2023-04-01' = if (usePrivateEndpoint) {
  parent: privateEndpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'redis'
        properties: {
          privateDnsZoneId: privateDnsZone.id
        }
      }
    ]
  }
}

// --- Secrets -----------------------------------------------------------------

resource kvPrimaryKey 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = if (hasKeyVault) {
  name: '${keyVaultName}/redis-primary-key'
  properties: {
    value: redisCache.listKeys().primaryKey
    contentType: 'text/plain'
  }
}

resource kvConnectionString 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = if (hasKeyVault) {
  name: '${keyVaultName}/redis-connection-string'
  properties: {
    value: 'rediss://:${redisCache.listKeys().primaryKey}@${hostName}:${sslPort}/0?ssl_cert_reqs=required'
    contentType: 'text/plain'
  }
}

resource kvHostname 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = if (hasKeyVault) {
  name: '${keyVaultName}/redis-hostname'
  properties: {
    value: hostName
    contentType: 'text/plain'
  }
}

output cacheName string = redisCache.name
output cacheId string = redisCache.id
output hostname string = hostName
output sslPort int = sslPort
