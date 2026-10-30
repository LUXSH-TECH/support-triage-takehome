// ILLUSTRATIVE — NOT DEPLOYED OR TESTED. Placeholders in <angle brackets>.
// Shows: Container App with a user-assigned managed identity, Key Vault secret references,
// HTTP concurrency scaling, health probes, and least-privilege role assignments.
// Validate with:  az bicep build -f infra/main.bicep
//                 az deployment group what-if -g <rg-triage-sandbox> -f infra/main.bicep -p image=<acr>.azurecr.io/triage:<sha>

param location string = resourceGroup().location
param image string                               // e.g. <acr>.azurecr.io/triage:<git-sha>
param environmentId string                       // existing Container Apps environment (VNet-integrated)
param keyVaultName string = 'kv-triage-prod'
param acrName string = '<acrname>'
param openAiName string = '<aoai-account>'
param pgHost string = '<pg-server>.postgres.database.azure.com'

resource uami 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-triage-api'
  location: location
}

resource kv 'Microsoft.KeyVault/vaults@2023-07-01' existing = { name: keyVaultName }
resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' existing = { name: acrName }
resource aoai 'Microsoft.CognitiveServices/accounts@2024-04-01-preview' existing = { name: openAiName }

// Built-in role definition IDs
var kvSecretsUser = '4633458b-17de-408a-b874-0445c86b69e6'   // Key Vault Secrets User
var acrPull       = '7f951dda-4ed3-4680-a7ca-43fe172d538d'   // AcrPull
var openAiUser    = '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'   // Cognitive Services OpenAI User

resource kvRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: kv
  name: guid(kv.id, uami.id, kvSecretsUser)
  properties: { principalId: uami.properties.principalId, principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', kvSecretsUser) }
}
resource acrRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: acr
  name: guid(acr.id, uami.id, acrPull)
  properties: { principalId: uami.properties.principalId, principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPull) }
}
resource aoaiRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: aoai
  name: guid(aoai.id, uami.id, openAiUser)
  properties: { principalId: uami.properties.principalId, principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', openAiUser) }
}
// PostgreSQL access is NOT an Azure RBAC role: map the MI to DB role `triage_app` once, e.g.
//   SELECT * FROM pgaadauth_create_principal('id-triage-api', false, false);
//   GRANT SELECT ON policy, api_client TO "id-triage-api"; GRANT INSERT ON triage_log TO "id-triage-api";

resource app 'Microsoft.App/containerApps@2024-03-01' = {
  name: 'triage-api'
  location: location
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${uami.id}': {} } }
  properties: {
    environmentId: environmentId
    configuration: {
      activeRevisionsMode: 'Multiple'              // enables traffic splitting + instant rollback
      ingress: { external: false, targetPort: 8000, transport: 'http' }   // reached via APIM only
      registries: [ { server: '${acrName}.azurecr.io', identity: uami.id } ]
      secrets: [
        // Key Vault references resolved with the managed identity; no secret values in config.
        { name: 'api-keys-json', keyVaultUrl: 'https://${keyVaultName}.vault.azure.net/secrets/api-keys-json', identity: uami.id }
        { name: 'erp-api-credential', keyVaultUrl: 'https://${keyVaultName}.vault.azure.net/secrets/erp-api-credential', identity: uami.id }
      ]
    }
    template: {
      containers: [ {
        name: 'api'
        image: image
        resources: { cpu: json('0.5'), memory: '1Gi' }
        env: [
          { name: 'AZURE_CLIENT_ID', value: uami.properties.clientId }
          // PLACEHOLDER: production would use Entra token auth for Postgres (no password);
          // the token-provider hook is not implemented in this repo.
          { name: 'DATABASE_URL', value: 'postgresql+psycopg://id-triage-api@${pgHost}:5432/triage?sslmode=require' }
          { name: 'LLM_PROVIDER', value: 'azure_openai' }
          { name: 'LLM_BASE_URL', value: 'https://${openAiName}.openai.azure.com' }
          { name: 'LLM_AZURE_DEPLOYMENT', value: '<deployment-name>' }
          { name: 'LLM_TIMEOUT_S', value: '8' }
          { name: 'LLM_MAX_RETRIES', value: '1' }
          { name: 'ERP_TIMEOUT_S', value: '2' }
          { name: 'API_KEYS_JSON', secretRef: 'api-keys-json' }   // day-one; hashed keys in DB later
        ]
        probes: [
          { type: 'Liveness',  httpGet: { path: '/health', port: 8000 }, periodSeconds: 30, failureThreshold: 3 }
          { type: 'Readiness', httpGet: { path: '/health', port: 8000 }, periodSeconds: 10, failureThreshold: 2 }
        ]
      } ]
      scale: {
        minReplicas: 2
        maxReplicas: 10
        rules: [ { name: 'http-concurrency', http: { metadata: { concurrentRequests: '40' } } } ]
      }
    }
  }
}
