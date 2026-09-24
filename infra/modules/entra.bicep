// Entra ID (Azure AD) app registration for SSO.
// Uses Microsoft Graph API for app registration.
// Note: Requires 'Microsoft.Graph' resource provider registration.
@description('Environment name (dev/prod) for app display name.')
param environmentName string

@description('Frontend SPA URL for redirect URI.')
param frontendUrl string

@description('Web API URL (optional, for backend).')
param apiUrl string = ''

@description('Reply URLs for the application.')
param replyUrls array = []

var displayName = 'PMO Risk Recurrence Predictor (${environmentName})'
var appId = '00000000-0000-0000-0000-000000000000'  // Placeholder - filled by Graph API call

// Note: Bicep cannot directly create Entra ID app registrations.
// This module documents the configuration and the app registration should be done via:
// 1. Azure Portal
// 2. Microsoft Graph API (separate script)
// 3. Azure CLI: az ad app create
//
// Required configuration:
// - Authentication: SPA with PKCE, redirect URIs
// - API permissions: Microsoft Graph User.Read
// - Token configuration: ID tokens, access tokens

output displayName string = displayName
output environmentName string = environmentName
output requiredReplyUrls array = concat([
  frontendUrl
  '${frontendUrl}/auth/callback'
], replyUrls)

// Script to create the app registration (run with Azure CLI / Graph API)
output appRegistrationCommands string = '''
# Create Entra ID app registration
# Requires Microsoft.Graph PowerShell module or az CLI with graph extension

# Option 1: Using az CLI (requires azure-cli with graph extension)
az extension add --name azure-devops
az ad app create \
  --display-name "${displayName}" \
  --auth-no-consent \
  --sign-audience AzureADMyOrg \
  --web-redirect-uris "${frontendUrl}" "${frontendUrl}/auth/callback" \
  --enable-access-token-issuance true \
  --enable-id-token-issuance true \
  --required-resource-access @manifest.json

# Option 2: Using Microsoft Graph PowerShell
# Install-Module Microsoft.Graph -Scope CurrentUser
# Connect-MgGraph -Scopes "Application.ReadWrite.All", "Directory.ReadWrite.All"
# New-MgApplication -DisplayName "${displayName}" ...
'''
