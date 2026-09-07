// Generic Azure Container App (consumption plan).
//
// Secrets passed in `secrets` (array of { name: <RISKAPP_* var name>, value })
// are stored as container-app secrets and exposed to the process as env vars
// of the same name via secretRef (secret stored under a lowercase name).
// Plain env vars in `envVars` are set directly.
@description('Container App resource name.')
param name string

@description('Azure region.')
param location string

@description('Managed environment resource id.')
param environmentId string

@description('Registry server e.g. myacr.azurecr.io.')
param registryServer string

@description('Full image reference, e.g. myacr.azurecr.io/riskapp-backend:sha.')
param image string

@description('Registry admin username.')
param registryUsername string

@description('Registry admin password (stored as a container-app secret).')
@secure()
param registryPassword string

@description('Plain (non-secret) env vars: array of { name, value }.')
param envVars array = []

@description('Secret env vars: array of { name: <VAR_NAME>, value }. Stored as container-app secrets and referenced by env var <VAR_NAME>.')
param secrets array = []

@description('Container command override (e.g. celery worker). Empty = image CMD.')
param command array = []

@description('Expose the app publicly via HTTPS ingress.')
param externalIngress bool = false

@description('Ingress target port. 0 disables ingress (background apps).')
param targetPort int = 0

@description('Minimum running replicas.')
param minReplicas int = 1

@description('Maximum running replicas.')
param maxReplicas int = 2

@description('HTTP concurrency for the HTTP autoscaler rule (empty = no rule).')
param httpConcurrency string = ''

@description('vCPU per replica (consumption plan).')
param cpu string = '0.5'

@description('Memory per replica (consumption plan).')
param memory string = '1Gi'

var secretDefs = [for s in secrets: {
  name: toLower(replace(s.name, '_', '-'))
  value: s.value
}]

var secretRefEnv = [for s in secrets: {
  name: s.name
  secretRef: toLower(replace(s.name, '_', '-'))
}]

var containerEnv = concat(envVars, secretRefEnv)

resource app 'Microsoft.App/containerApps@2024-03-01' = {
  name: name
  location: location
  properties: {
    managedEnvironmentId: environmentId
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: targetPort > 0 ? {
        external: externalIngress
        targetPort: targetPort
        allowInsecure: false
        traffic: [
          {
            latestRevision: true
            weight: 100
          }
        ]
      } : null
      registries: [
        {
          server: registryServer
          username: registryUsername
          passwordSecretRef: 'registry-password'
        }
      ]
      secrets: concat(secretDefs, [
        {
          name: 'registry-password'
          value: registryPassword
        }
      ])
    }
    template: {
      containers: [
        {
          name: name
          image: image
          command: command
          env: containerEnv
          resources: {
            cpu: json(cpu)
            memory: memory
          }
        }
      ]
      scale: {
        minReplicas: minReplicas
        maxReplicas: maxReplicas
        rules: httpConcurrency != '' ? [
          {
            name: 'http'
            custom: {
              type: 'http'
              metadata: {
                concurrency: httpConcurrency
              }
            }
          }
        ] : []
      }
    }
  }
}

output fqdn string = targetPort > 0 ? app.properties.configuration.ingress.fqdn : ''
output id string = app.id
