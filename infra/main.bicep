// =============================================================================
// PMO Risk Recurrence Predictor — Deploy any service (Container Apps)
// =============================================================================
//
// One template, every service. Use it to (re)deploy the whole application or a
// single service — the web API, the Celery worker, the Celery beat scheduler or
// the nginx frontend — against the existing Container Registry + Container Apps
// Environment.
//
//   web      : FastAPI API (runs `alembic upgrade head` on start)
//   worker   : Celery worker
//   beat     : Celery beat scheduler
//   frontend : nginx-served React SPA (proxies /api to web)
//
// The environment and registry modules are idempotent: re-running the template
// simply ensures they exist, so the same file is safe for a full deploy or for
// a single-service refresh (set the other `deploy*` toggles to false).
//
// Runtime configuration arrives through three parameters:
//   appEnv       : plain (non-secret) environment variables, shared by the
//                  backend services (web/worker/beat).
//   appSecrets   : secret values registered on each app, array of { name, value }.
//   appSecretRefs: env vars bound to a secret, array of { name, secretName }.
//
// This keeps every value out of the template itself and lets callers inject
// Key Vault references or plain strings without editing the Bicep.
//
// For a full end-to-end provisioning run (ACR, Postgres, Redis, Storage,
// OpenAI, Key Vault, …) use main-complete.bicep instead. The companion script
// infra/deploy-service.sh (or .ps1) drives this template.
//
// =============================================================================

targetScope = 'resourceGroup'

// -----------------------------------------------------------------------------
// CORE PARAMETERS
// -----------------------------------------------------------------------------

@description('Environment suffix: dev | prod.')
param environmentName string

@description('Azure region.')
param location string = resourceGroup().location

@description('Infrastructure subnet resource ID for the Container Apps environment (empty = public). Re-applied on re-runs so private networking is preserved.')
param infrastructureSubnetId string = ''

@description('Use an internal load balancer for the environment (private networking).')
param internalLoadBalancer bool = false

@description('Name prefix for all resources.')
param prefix string = 'riskapp'

@description('Container registry name.')
param acrName string

@description('Image tag to deploy.')
param imageTag string = 'latest'

@description('Backend image repository name (web/worker/beat).')
param backendImageName string = 'riskapp-backend'

@description('Frontend image repository name.')
param frontendImageName string = 'riskapp-frontend'

// -----------------------------------------------------------------------------
// WHICH SERVICES TO DEPLOY
// -----------------------------------------------------------------------------

@description('Deploy the FastAPI web app.')
param deployWeb bool = true

@description('Deploy the Celery worker.')
param deployWorker bool = true

@description('Deploy the Celery beat scheduler.')
param deployBeat bool = true

@description('Deploy the nginx frontend.')
param deployFrontend bool = true

// -----------------------------------------------------------------------------
// RUNTIME CONFIGURATION
// -----------------------------------------------------------------------------

@description('Plain env vars shared by web/worker/beat: array of { name, value }.')
param appEnv array = []

@description('Extra plain env vars, web only: array of { name, value }.')
param webExtraEnv array = []

@description('Secret values registered on each app: array of { name, value }.')
param appSecrets array = []

@description('Env vars bound to secrets: array of { name, secretName }.')
param appSecretRefs array = []

// -----------------------------------------------------------------------------
// IDENTITY / REGISTRY AUTH
// -----------------------------------------------------------------------------

@description('User-assigned managed identity resource ID used by the apps.')
param managedIdentityId string = ''

@description('Principal ID of the managed identity, granted AcrPull.')
param managedIdentityPrincipalId string = ''

@description('Registry resource ID for managed-identity image pulls. Takes precedence over credentials.')
param registryIdentityId string = ''

@description('Registry admin username (only when registryIdentityId is empty).')
param registryUsername string = ''

@description('Registry admin password (only when registryIdentityId is empty).')
@secure()
param registryPassword string = ''

// -----------------------------------------------------------------------------
// SCALING
// -----------------------------------------------------------------------------

param webMinReplicas int = 1
param webMaxReplicas int = 2
param workerMinReplicas int = 1
param workerMaxReplicas int = 2
param beatMinReplicas int = 1
param frontendMinReplicas int = 1
param frontendMaxReplicas int = 2

// -----------------------------------------------------------------------------
// VARIABLES
// -----------------------------------------------------------------------------

var envResourceName = '${prefix}-${environmentName}-env'
var webAppName = '${prefix}-${environmentName}-web'
var workerAppName = '${prefix}-${environmentName}-worker'
var beatAppName = '${prefix}-${environmentName}-beat'
var frontendAppName = '${prefix}-${environmentName}-frontend'

// -----------------------------------------------------------------------------
// CONTAINER REGISTRY + ENVIRONMENT (idempotent — ensures they exist)
// -----------------------------------------------------------------------------

module registry './modules/registry.bicep' = {
  name: 'acr'
  params: {
    name: acrName
    location: location
    managedIdentityPrincipalId: managedIdentityPrincipalId
  }
}

module environment './modules/environment.bicep' = {
  name: 'environment'
  params: {
    name: envResourceName
    location: location
    infrastructureSubnetId: infrastructureSubnetId
    internalLoadBalancer: internalLoadBalancer
  }
}

var acrLoginServer = registry.outputs.loginServer
var backendImage = '${acrLoginServer}/${backendImageName}:${imageTag}'
var frontendImage = '${acrLoginServer}/${frontendImageName}:${imageTag}'
var apiUpstream = 'https://${webAppName}.${environment.outputs.defaultDomain}'

// Backend env vars: shared appEnv + the environment name + web-only extras.
var backendEnvVars = concat(
  appEnv,
  [
    {
      name: 'RISKAPP_ENVIRONMENT'
      value: environmentName
    }
  ]
)

// -----------------------------------------------------------------------------
// WEB (FastAPI) — runs migrations, then serves the API
// -----------------------------------------------------------------------------

module web 'modules/container-app.bicep' = if (deployWeb) {
  name: 'web-app'
  params: {
    name: webAppName
    location: location
    environmentId: environment.outputs.id
    registryServer: acrLoginServer
    image: backendImage
    registryIdentityId: registryIdentityId
    registryUsername: registryUsername
    registryPassword: registryPassword
    envVars: concat(backendEnvVars, webExtraEnv)
    secrets: appSecrets
    secretRefs: appSecretRefs
    command: [
      '/bin/sh'
      '-c'
      'alembic upgrade head && uvicorn riskapp.main:app --host 0.0.0.0 --port 8000'
    ]
    externalIngress: true
    targetPort: 8000
    minReplicas: webMinReplicas
    maxReplicas: webMaxReplicas
    httpConcurrency: '80'
    managedIdentityId: managedIdentityId
  }
}

// -----------------------------------------------------------------------------
// WORKER (Celery)
// -----------------------------------------------------------------------------

module worker 'modules/container-app.bicep' = if (deployWorker) {
  name: 'worker-app'
  params: {
    name: workerAppName
    location: location
    environmentId: environment.outputs.id
    registryServer: acrLoginServer
    image: backendImage
    registryIdentityId: registryIdentityId
    registryUsername: registryUsername
    registryPassword: registryPassword
    envVars: backendEnvVars
    secrets: appSecrets
    secretRefs: appSecretRefs
    command: [
      'celery'
      '-A'
      'riskapp.celery_app:celery_app'
      'worker'
      '--loglevel=INFO'
    ]
    targetPort: 0
    minReplicas: workerMinReplicas
    maxReplicas: workerMaxReplicas
    managedIdentityId: managedIdentityId
  }
}

// -----------------------------------------------------------------------------
// BEAT (Celery scheduler) — single replica only
// -----------------------------------------------------------------------------

module beat 'modules/container-app.bicep' = if (deployBeat) {
  name: 'beat-app'
  params: {
    name: beatAppName
    location: location
    environmentId: environment.outputs.id
    registryServer: acrLoginServer
    image: backendImage
    registryIdentityId: registryIdentityId
    registryUsername: registryUsername
    registryPassword: registryPassword
    envVars: backendEnvVars
    secrets: appSecrets
    secretRefs: appSecretRefs
    command: [
      'celery'
      '-A'
      'riskapp.celery_app:celery_app'
      'beat'
      '--loglevel=INFO'
    ]
    targetPort: 0
    minReplicas: beatMinReplicas
    maxReplicas: 1
    managedIdentityId: managedIdentityId
  }
}

// -----------------------------------------------------------------------------
// FRONTEND (nginx serving the SPA, proxying /api to web)
// -----------------------------------------------------------------------------

module frontend 'modules/container-app.bicep' = if (deployFrontend) {
  name: 'frontend-app'
  params: {
    name: frontendAppName
    location: location
    environmentId: environment.outputs.id
    registryServer: acrLoginServer
    image: frontendImage
    registryIdentityId: registryIdentityId
    registryUsername: registryUsername
    registryPassword: registryPassword
    envVars: [
      {
        name: 'API_UPSTREAM'
        value: apiUpstream
      }
    ]
    secrets: []
    secretRefs: []
    command: []
    externalIngress: true
    targetPort: 80
    minReplicas: frontendMinReplicas
    maxReplicas: frontendMaxReplicas
    httpConcurrency: '120'
    managedIdentityId: managedIdentityId
  }
}

// -----------------------------------------------------------------------------
// OUTPUTS
// -----------------------------------------------------------------------------

output acrLoginServer string = acrLoginServer
output backendImage string = backendImage
output frontendImage string = frontendImage

output containerEnvironmentName string = envResourceName
output containerEnvironmentId string = environment.outputs.id
output containerEnvironmentDefaultDomain string = environment.outputs.defaultDomain

output webAppName string = deployWeb ? webAppName : ''
#disable-next-line BCP318
output webFqdn string = deployWeb ? web.outputs.fqdn : ''
output workerAppName string = deployWorker ? workerAppName : ''
output beatAppName string = deployBeat ? beatAppName : ''
output frontendAppName string = deployFrontend ? frontendAppName : ''
#disable-next-line BCP318
output frontendFqdn string = deployFrontend ? frontend.outputs.fqdn : ''
output apiUpstream string = apiUpstream
