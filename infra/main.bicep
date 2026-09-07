// PMO Risk Recurrence Predictor — Azure Container Apps infrastructure.
//
// Deploy into an existing resource group (the deploy scripts create it):
//   az deployment group create -g <rg> -f infra/main.bicep --parameters ...
//
// Two phases (see infra/deploy.sh / .github/workflows/deploy.yml):
//   1. deployApps = false  -> resource group content: ACR + environment.
//   2. push images to ACR, then deployApps = true -> the four container apps.
//
// Topology (matches docker-compose services):
//   web       FastAPI + migrations, public HTTPS ingress (port 8000)
//   worker    Celery worker (no ingress)
//   beat      Celery beat (no ingress)
//   frontend  nginx SPA, public HTTPS ingress (port 80), proxies /api -> web
//             (API_UPSTREAM is injected from the web app's FQDN)
targetScope = 'resourceGroup'

@description('Environment suffix: dev | prod.')
param environmentName string

@description('Azure region (resources in backend/.env are eastus).')
param location string = 'eastus'

@description('Name prefix for all resources.')
param prefix string = 'riskapp'

@description('Container registry name (must be globally unique).')
param acrName string

@description('Image tag to deploy.')
param imageTag string = 'latest'

@description('Backend image repository name.')
param backendImageName string = 'riskapp-backend'

@description('Frontend image repository name.')
param frontendImageName string = 'riskapp-frontend'

@description('false = provision ACR + environment only (before images exist).')
param deployApps bool = true

@description('Plain env vars shared by every app: array of { name, value }.')
param appEnv array = []

@description('Secret env vars shared by every app: array of { name: <RISKAPP_*>, value }.')
param appSecrets array = []

param webMinReplicas int = 1
param webMaxReplicas int = 2
param workerMinReplicas int = 1
param workerMaxReplicas int = 2
param beatMinReplicas int = 1

var envResourceName = '${prefix}-${environmentName}-env'
var webAppName = '${prefix}-${environmentName}-web'
var workerAppName = '${prefix}-${environmentName}-worker'
var beatAppName = '${prefix}-${environmentName}-beat'
var frontendAppName = '${prefix}-${environmentName}-frontend'

module registry './modules/registry.bicep' = {
  name: 'acr'
  params: {
    name: acrName
    location: location
  }
}

module environment './modules/environment.bicep' = {
  name: 'environment'
  params: {
    name: envResourceName
    location: location
  }
}

// Frontend proxies /api to the web container app. The web app FQDN is
// deterministic: <app>.<environment defaultDomain>. nginx (frontend image)
// substitutes ${API_UPSTREAM} from this env var at container start.
var apiUpstream = 'https://${webAppName}.${environment.outputs.defaultDomain}'

var backendEnv = concat(appEnv, [
  {
    name: 'RISKAPP_ENVIRONMENT'
    value: environmentName
  }
])

module web 'modules/container-app.bicep' = if (deployApps) {
  name: 'web-app'
  params: {
    name: webAppName
    location: location
    environmentId: environment.outputs.id
    registryServer: registry.outputs.loginServer
    image: '${registry.outputs.loginServer}/${backendImageName}:${imageTag}'
    registryUsername: registry.outputs.username
    registryPassword: registry.outputs.password
    envVars: backendEnv
    secrets: appSecrets
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
  }
}

module worker 'modules/container-app.bicep' = if (deployApps) {
  name: 'worker-app'
  params: {
    name: workerAppName
    location: location
    environmentId: environment.outputs.id
    registryServer: registry.outputs.loginServer
    image: '${registry.outputs.loginServer}/${backendImageName}:${imageTag}'
    registryUsername: registry.outputs.username
    registryPassword: registry.outputs.password
    envVars: backendEnv
    secrets: appSecrets
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
  }
}

module beat 'modules/container-app.bicep' = if (deployApps) {
  name: 'beat-app'
  params: {
    name: beatAppName
    location: location
    environmentId: environment.outputs.id
    registryServer: registry.outputs.loginServer
    image: '${registry.outputs.loginServer}/${backendImageName}:${imageTag}'
    registryUsername: registry.outputs.username
    registryPassword: registry.outputs.password
    envVars: backendEnv
    secrets: appSecrets
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
  }
}

module frontend 'modules/container-app.bicep' = if (deployApps) {
  name: 'frontend-app'
  params: {
    name: frontendAppName
    location: location
    environmentId: environment.outputs.id
    registryServer: registry.outputs.loginServer
    image: '${registry.outputs.loginServer}/${frontendImageName}:${imageTag}'
    registryUsername: registry.outputs.username
    registryPassword: registry.outputs.password
    envVars: [
      {
        name: 'API_UPSTREAM'
        value: apiUpstream
      }
    ]
    secrets: []
    command: []
    externalIngress: true
    targetPort: 80
    minReplicas: 1
    maxReplicas: 2
    httpConcurrency: '120'
  }
}

output webAppName string = webAppName
output workerAppName string = workerAppName
output beatAppName string = beatAppName
output frontendAppName string = frontendAppName
output apiUpstream string = apiUpstream
