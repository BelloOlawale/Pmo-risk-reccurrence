// =============================================================================
// Azure Database for PostgreSQL Flexible Server Module
// =============================================================================
//
// Deploys PostgreSQL Flexible Server (v16) with:
//   - pgvector available via the azure.extensions server parameter
//   - An application database
//   - Optional private endpoint + private DNS zone
//   - Connection details stored in Key Vault
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

@description('PostgreSQL administrator login.')
param adminUsername string

@description('PostgreSQL administrator password.')
@secure()
param adminPassword string

@description('Storage size in GB.')
param storageSizeGb int = 32

@description('PostgreSQL SKU name.')
param skuName string = 'Standard_B2s'

@description('PostgreSQL compute tier.')
@allowed([
  'Burstable'
  'GeneralPurpose'
  'MemoryOptimized'
])
param tier string = 'Burstable'

@description('PostgreSQL major version.')
@allowed([
  '15'
  '16'
  '17'
])
param postgresVersion string = '16'

@description('Application database name.')
param databaseName string = 'riskapp'

@description('Key Vault name used to store connection secrets (empty to skip).')
param keyVaultName string = ''

@description('Private endpoint subnet resource ID (empty for public access).')
param privateEndpointSubnetId string = ''

@description('Virtual Network resource ID (required when using a private endpoint).')
param vnetId string = ''

@description('Virtual Network name (required when using a private endpoint).')
param vnetName string = ''

@description('Enable geo-redundant backup.')
param geoRedundantBackup bool = false

var serverName = !empty(uniqueSuffix) ? '${prefix}-${environmentName}-postgres${uniqueSuffix}' : '${prefix}-${environmentName}-postgres'
var fqdn = '${serverName}.postgres.database.azure.com'
var usePrivateEndpoint = !empty(privateEndpointSubnetId)
var hasKeyVault = !empty(keyVaultName)

// PostgreSQL Flexible Server
resource server 'Microsoft.DBforPostgreSQL/flexibleServers@2024-08-01' = {
  name: serverName
  location: location
  sku: {
    name: skuName
    tier: tier
  }
  properties: {
    administratorLogin: adminUsername
    administratorLoginPassword: adminPassword
    version: postgresVersion
    storage: {
      storageSizeGB: storageSizeGb
    }
    highAvailability: {
      mode: 'Disabled'
    }
    backup: {
      backupRetentionDays: 7
      geoRedundantBackup: geoRedundantBackup ? 'Enabled' : 'Disabled'
    }
    network: {
      publicNetworkAccess: usePrivateEndpoint ? 'Disabled' : 'Enabled'
    }
  }
}

// Application database
resource database 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2024-08-01' = {
  parent: server
  name: databaseName
  properties: {
    charset: 'UTF8'
    collation: 'en_US.utf8'
  }
}

// Allow the pgvector extension (must also be CREATEd inside the database)
resource azureExtensions 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-08-01' = {
  parent: server
  name: 'azure.extensions'
  properties: {
    value: 'VECTOR'
    source: 'user-defined'
  }
}

// Allow Azure services through the firewall when the server is public
resource allowAzureServicesFirewallRule 'Microsoft.DBforPostgreSQL/flexibleServers/firewallRules@2024-08-01' = if (!usePrivateEndpoint) {
  parent: server
  name: 'AllowAllAzureServices'
  properties: {
    startIpAddress: '0.0.0.0'
    endIpAddress: '0.0.0.0'
  }
}

// --- Private networking -----------------------------------------------------

resource privateDnsZone 'Microsoft.Network/privateDnsZones@2020-06-01' = if (usePrivateEndpoint) {
  name: 'privatelink.postgres.database.azure.com'
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
  name: '${serverName}-pe'
  location: location
  properties: {
    subnet: {
      id: privateEndpointSubnetId
    }
    privateLinkServiceConnections: [
      {
        name: '${serverName}-pls'
        properties: {
          privateLinkServiceId: server.id
          groupIds: [
            'postgresqlServer'
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
        name: 'postgres'
        properties: {
          privateDnsZoneId: privateDnsZone.id
        }
      }
    ]
  }
}

// --- Secrets -----------------------------------------------------------------

resource kvConnectionString 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = if (hasKeyVault) {
  name: '${keyVaultName}/postgresql-connection-string'
  properties: {
    value: 'postgresql+psycopg://${adminUsername}:${adminPassword}@${fqdn}:5432/${databaseName}?sslmode=require'
    contentType: 'text/plain'
  }
}

resource kvHostSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = if (hasKeyVault) {
  name: '${keyVaultName}/postgresql-host'
  properties: {
    value: fqdn
    contentType: 'text/plain'
  }
}

resource kvDatabaseSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = if (hasKeyVault) {
  name: '${keyVaultName}/postgresql-database'
  properties: {
    value: databaseName
    contentType: 'text/plain'
  }
}

output serverName string = server.name
output serverId string = server.id
output fqdn string = fqdn
output databaseName string = databaseName
output connectionStringSecretName string = 'postgresql-connection-string'
