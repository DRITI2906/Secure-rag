// Secure RAG service — Azure infrastructure (free-tier-friendly)
//
// Deploys: Log Analytics + Application Insights, User-Assigned Managed Identity,
// Key Vault (RBAC mode), Storage (private), Azure Container Registry,
// Container Apps Environment, Container App, and the RBAC role assignments
// wiring it all together.
//
// SECURITY POSTURE
// - Managed Identity for every internal hop (KV, ACR, Storage). No keys in code.
// - Key Vault in RBAC mode (no access policies); MI granted ONLY Key Vault Secrets User.
// - Storage: shared-key access DISABLED, no anonymous blobs, TLS 1.2 minimum.
// - ACR: admin user DISABLED; MI granted ONLY AcrPull.
// - Container App: scale-to-zero (minReplicas 0), capped maxReplicas, HTTPS ingress.
// - App Insights / Log Analytics: 30-day retention (short; logs are a PII surface).
//
// Deploy:
//   az group create -n rg-clustral-rag -l eastus
//   az deployment group create -g rg-clustral-rag -f infra/main.bicep -p resourcePrefix=clustral

targetScope = 'resourceGroup'

@description('Short prefix for all resource names. 3-8 lowercase letters/digits.')
@minLength(3)
@maxLength(8)
param resourcePrefix string

@description('Azure region for all resources.')
param location string = resourceGroup().location

@description('Container image to deploy. The default is a placeholder so the infra stands up before the real image is built; update after first deploy.')
param containerImage string = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'

// ---------- naming ----------
var suffix = substring(uniqueString(resourceGroup().id), 0, 6)
var keyVaultName  = '${resourcePrefix}kv${suffix}'
var storageName   = toLower('${resourcePrefix}st${suffix}')
var acrName       = toLower('${resourcePrefix}acr${suffix}')
var logName       = '${resourcePrefix}-log'
var appiName      = '${resourcePrefix}-appi'
var envName       = '${resourcePrefix}-env'
var appName       = '${resourcePrefix}-app'
var uamiName      = '${resourcePrefix}-uami'

// ---------- Log Analytics + Application Insights ----------
resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: logName
  location: location
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
    features: { enableLogAccessUsingOnlyResourcePermissions: true }
  }
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: appiName
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logAnalytics.id
    publicNetworkAccessForIngestion: 'Enabled'
    publicNetworkAccessForQuery: 'Enabled'
  }
}

// ---------- User-Assigned Managed Identity ----------
// Attached to the Container App; used to authenticate to KV, ACR, and Storage
// without ever holding a credential in code or env vars.
resource uami 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: uamiName
  location: location
}

// ---------- Key Vault (RBAC, soft-delete on) ----------
resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: keyVaultName
  location: location
  properties: {
    sku: { family: 'A', name: 'standard' }
    tenantId: subscription().tenantId
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 7
    publicNetworkAccess: 'Enabled'   // free-tier: no private endpoint; mitigated by RBAC + MI + TLS
    networkAcls: { defaultAction: 'Allow', bypass: 'AzureServices' }
  }
}

// ---------- Storage Account (no public, no shared-key) ----------
resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: storageName
  location: location
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
  properties: {
    accessTier: 'Hot'
    allowBlobPublicAccess: false        // no public blobs
    allowSharedKeyAccess: false         // force MI / RBAC auth, no account keys
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    publicNetworkAccess: 'Enabled'
    networkAcls: { defaultAction: 'Allow', bypass: 'AzureServices' }
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storage
  name: 'default'
  properties: {
    deleteRetentionPolicy: { enabled: true, days: 7 }
  }
}

resource ragContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: 'rag-index'
  properties: { publicAccess: 'None' }
}

// ---------- Azure Container Registry (admin disabled) ----------
resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: acrName
  location: location
  sku: { name: 'Basic' }
  properties: {
    adminUserEnabled: false   // forces MI-based pulls; no admin password to leak
    publicNetworkAccess: 'Enabled'
  }
}

// ---------- Container Apps Environment ----------
resource containerEnv 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: envName
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalytics.properties.customerId
        sharedKey: logAnalytics.listKeys().primarySharedKey
      }
    }
    workloadProfiles: [
      { name: 'Consumption', workloadProfileType: 'Consumption' }
    ]
  }
}

// ---------- RBAC role IDs ----------
var kvSecretsUserRoleId = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '4633458b-17de-408a-b874-0445c86b69e6')
var acrPullRoleId       = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '7f951dda-4ed3-4680-a7ca-43fe172d538d')
var blobReaderRoleId    = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '2a2b9908-6ea1-4ae2-8e65-a410df84e7d1')

resource uamiKvSecretsUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: keyVault
  name: guid(keyVault.id, uami.id, 'KVSecretsUser')
  properties: {
    roleDefinitionId: kvSecretsUserRoleId
    principalId: uami.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource uamiAcrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: acr
  name: guid(acr.id, uami.id, 'AcrPull')
  properties: {
    roleDefinitionId: acrPullRoleId
    principalId: uami.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource uamiBlobReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: storage
  name: guid(storage.id, uami.id, 'BlobReader')
  properties: {
    roleDefinitionId: blobReaderRoleId
    principalId: uami.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// ---------- Container App ----------
resource containerApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: appName
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${uami.id}': {} }
  }
  properties: {
    managedEnvironmentId: containerEnv.id
    workloadProfileName: 'Consumption'
    configuration: {
      ingress: {
        external: true
        targetPort: 8000
        transport: 'http'
        allowInsecure: false
        traffic: [ { weight: 100, latestRevision: true } ]
      }
      registries: [
        {
          server: acr.properties.loginServer
          identity: uami.id
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'rag'
          image: containerImage
          resources: { cpu: json('1.0'), memory: '2Gi' }
          env: [
            { name: 'KEY_VAULT_URI',                          value: keyVault.properties.vaultUri }
            { name: 'KEY_VAULT_SECRET_NAME',                  value: 'groq-api-key' }
            { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING',  value: appInsights.properties.ConnectionString }
            { name: 'BLOB_ACCOUNT_URL',                       value: 'https://${storage.name}.blob.${environment().suffixes.storage}' }
            { name: 'BLOB_CONTAINER',                         value: 'rag-index' }
            { name: 'AZURE_CLIENT_ID',                        value: uami.properties.clientId }   // tells DefaultAzureCredential WHICH UAMI
          ]
        }
      ]
      scale: {
        minReplicas: 0    // scale-to-zero cost ceiling
        maxReplicas: 2    // hard burst cap
      }
    }
  }
  dependsOn: [
    uamiKvSecretsUser
    uamiAcrPull
    uamiBlobReader
  ]
}

// ---------- outputs ----------
output containerAppFqdn string = containerApp.properties.configuration.ingress.fqdn
output keyVaultName     string = keyVault.name
output keyVaultUri      string = keyVault.properties.vaultUri
output acrLoginServer   string = acr.properties.loginServer
output acrName          string = acr.name
output blobAccountUrl   string = 'https://${storage.name}.blob.${environment().suffixes.storage}'
output uamiClientId     string = uami.properties.clientId
output uamiPrincipalId  string = uami.properties.principalId