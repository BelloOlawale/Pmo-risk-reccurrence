// Azure Container Registry for this environment's images.
@description('Container registry name (globally unique, lowercase alphanumerics only).')
param name string

@description('Azure region.')
param location string

@description('Registry SKU (Basic is fine for a single app).')
param sku string = 'Basic'

@description('Enable the registry admin account. The deployed container apps pull using these credentials. Switch to a managed identity before hardening.')
param adminEnabled bool = true

resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: name
  location: location
  sku: {
    name: sku
  }
  properties: {
    adminUserEnabled: adminEnabled
  }
}

output id string = registry.id
output loginServer string = registry.properties.loginServer

// The admin credentials are consumed by the container-app modules in this same
// deployment (registry auth secret), never shown to end users.
#disable-next-line outputs-should-not-contain-secrets // deploy-time registry auth, consumed in-template
output username string = adminEnabled ? registry.listCredentials().username : ''
#disable-next-line outputs-should-not-contain-secrets // deploy-time registry auth, consumed in-template
output password string = adminEnabled ? registry.listCredentials().passwords[0].value : ''
