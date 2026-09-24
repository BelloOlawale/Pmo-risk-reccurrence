// =============================================================================
// Azure Container App Module
// =============================================================================
//
// Generic Container App for Azure Container Apps (consumption plan).
// Supports a user-assigned managed identity, external/internal ingress,
// HTTP-based autoscaling, plain env vars, secret env vars, and image pulls
// via either managed identity or registry credentials.
//
// =============================================================================

@description('Container App resource name.')
param name string

@description('Azure region.')
param location string

@description('Container Apps Environment resource ID.')
param environmentId string

@description('Registry server (e.g. myacr.azurecr.io).')
param registryServer string

@description('Full image reference (e.g. myacr.azurecr.io/riskapp-backend:latest).')
param image string

@description('Registry resource ID used for managed-identity image pulls. Takes precedence over username/password.')
param registryIdentityId string = ''

@description('Registry admin username (used only when registryIdentityId is empty).')
param registryUsername string = ''

@description('Registry admin password (used only when registryIdentityId is empty).')
@secure()
param registryPassword string = ''

@description('Plain (non-secret) environment variables: array of { name, value }.')
param envVars array = []

@description('Secret values to register on the app: array of { name, value }.')
param secrets array = []

@description('Environment variables bound to secrets: array of { name, secretName }.')
param secretRefs array = []

@description('Container command override. Empty = image default CMD.')
param command array = []

@description('Enable external (public) HTTPS ingress.')
param externalIngress bool = false

@description('Ingress target port. Use 0 for background apps without ingress.')
param targetPort int = 0

@description('Minimum number of replicas.')
param minReplicas int = 1

@description('Maximum number of replicas.')
param maxReplicas int = 2

@description('Concurrent HTTP requests per replica for the HTTP autoscaler.')
param httpConcurrency string = ''

@description('User-assigned managed identity resource ID.')
param managedIdentityId string = ''

@description('CPU cores per replica (e.g. 0.5, 1, 2).')
param cpu string = '0.5'

@description('Memory per replica (e.g. 1Gi, 2Gi).')
param memory string = '1Gi'

var usesRegistryIdentity = !empty(registryIdentityId)

// Ingress configuration (null when the app has no ingress)
var ingressConfig = targetPort > 0 ? {
  external: externalIngress
  targetPort: targetPort
  allowInsecure: false
  transport: 'auto'
  traffic: [
    {
      latestRevision: true
      weight: 100
    }
  ]
} : null

// Registry configuration: managed identity or admin credentials
var registryConfig = usesRegistryIdentity ? {
  server: registryServer
  identity: registryIdentityId
} : {
  server: registryServer
  username: registryUsername
  passwordSecretRef: 'registry-password'
}

// Secrets registered on the app (registry password only when credentials are used)
var appSecrets = concat(
  usesRegistryIdentity ? [] : [
    {
      name: 'registry-password'
      value: registryPassword
    }
  ],
  secrets
)

// Secret-bound env vars (for-expressions must be assigned to their own variable)
var secretEnv = [for ref in secretRefs: {
  name: ref.name
  secretRef: ref.secretName
}]

// Plain env vars + secret-bound env vars
var appEnv = concat(envVars, secretEnv)

// HTTP autoscaling rule (optional)
var scaleRules = !empty(httpConcurrency) && targetPort > 0 ? [
  {
    name: 'http-scaling-rule'
    http: {
      metadata: {
        concurrentRequests: httpConcurrency
      }
    }
  }
] : []

resource containerApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: name
  location: location
  identity: !empty(managedIdentityId) ? {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${managedIdentityId}': {}
    }
  } : null
  properties: {
    managedEnvironmentId: environmentId
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: ingressConfig
      registries: [
        registryConfig
      ]
      secrets: appSecrets
    }
    template: {
      containers: [
        {
          name: name
          image: image
          command: !empty(command) ? command : null
          env: appEnv
          resources: {
            cpu: json(cpu)
            memory: memory
          }
        }
      ]
      scale: {
        minReplicas: minReplicas
        maxReplicas: maxReplicas
        rules: scaleRules
      }
    }
  }
}

output fqdn string = targetPort > 0 ? containerApp.properties.configuration.ingress.fqdn : ''
output id string = containerApp.id
output name string = containerApp.name
