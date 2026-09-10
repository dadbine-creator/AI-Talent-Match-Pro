#!/bin/bash
# ============================================================
# AI Talent Match Pro - Azure Deployment Script
# Phase 20 - Deploy AIGradeEngine to Azure Function App
# ============================================================

set -e

# CONFIGURATION
RESOURCE_GROUP="ai-talent-match-pro-rg"
LOCATION="eastus"
STORAGE_ACCOUNT="aitalentmatchstorage"
FUNCTION_APP_NAME="ai-talent-grade-engine"
COSMOS_ACCOUNT="ai-talent-cosmos"
COSMOS_DATABASE="talent_db"
COSMOS_CONTAINER="candidates"
APP_INSIGHTS_NAME="ai-talent-insights"

echo "Starting AI Talent Match Pro - Phase 20 Deployment"
echo "==================================================="

# STEP 1 - Create Resource Group
echo ""
echo "Step 1: Creating Resource Group..."
az group create \
    --name $RESOURCE_GROUP \
    --location $LOCATION \
    --output none
echo "Done: Resource Group created"

# STEP 2 - Create Storage Account
echo ""
echo "Step 2: Creating Storage Account..."
az storage account create \
    --name $STORAGE_ACCOUNT \
    --location $LOCATION \
    --resource-group $RESOURCE_GROUP \
    --sku Standard_LRS \
    --output none
echo "Done: Storage Account created"

# STEP 3 - Create Application Insights
echo ""
echo "Step 3: Creating Application Insights..."
az monitor app-insights component create \
    --app $APP_INSIGHTS_NAME \
    --location $LOCATION \
    --resource-group $RESOURCE_GROUP \
    --output none
APP_INSIGHTS_KEY=$(az monitor app-insights component show \
    --app $APP_INSIGHTS_NAME \
    --resource-group $RESOURCE_GROUP \
    --query instrumentationKey -o tsv)
echo "Done: Application Insights created"

# STEP 4 - Create Function App
echo ""
echo "Step 4: Creating Azure Function App..."
az functionapp create \
    --resource-group $RESOURCE_GROUP \
    --consumption-plan-location $LOCATION \
    --runtime python \
    --runtime-version 3.11 \
    --functions-version 4 \
    --name $FUNCTION_APP_NAME \
    --storage-account $STORAGE_ACCOUNT \
    --app-insights $APP_INSIGHTS_NAME \
    --os-type linux \
    --output none
echo "Done: Function App created"

# STEP 5 - Create CosmosDB
echo ""
echo "Step 5: Creating Azure CosmosDB..."
az cosmosdb create \
    --name $COSMOS_ACCOUNT \
    --resource-group $RESOURCE_GROUP \
    --locations regionName=$LOCATION \
    --kind GlobalDocumentDB \
    --output none

az cosmosdb sql database create \
    --account-name $COSMOS_ACCOUNT \
    --resource-group $RESOURCE_GROUP \
    --name $COSMOS_DATABASE \
    --output none

az cosmosdb sql container create \
    --account-name $COSMOS_ACCOUNT \
    --resource-group $RESOURCE_GROUP \
    --database-name $COSMOS_DATABASE \
    --name $COSMOS_CONTAINER \
    --partition-key-path "/role" \
    --throughput 400 \
    --output none

COSMOS_CONNECTION=$(az cosmosdb keys list \
    --name $COSMOS_ACCOUNT \
    --resource-group $RESOURCE_GROUP \
    --type connection-strings \
    --query connectionStrings[0].connectionString -o tsv)
echo "Done: CosmosDB created"

# STEP 6 - Set Environment Variables
echo ""
echo "Step 6: Setting environment variables..."
az functionapp config appsettings set \
    --name $FUNCTION_APP_NAME \
    --resource-group $RESOURCE_GROUP \
    --settings \
        "AZURE_OPENAI_API_KEY=$AZURE_OPENAI_API_KEY" \
        "AZURE_OPENAI_ENDPOINT=$AZURE_OPENAI_ENDPOINT" \
        "AZURE_OPENAI_API_VERSION=2024-02-01" \
        "AZURE_OPENAI_DEPLOYMENT=gpt-4o" \
        "COSMOS_CONNECTION_STRING=$COSMOS_CONNECTION" \
        "APPINSIGHTS_INSTRUMENTATIONKEY=$APP_INSIGHTS_KEY" \
    --output none
echo "Done: Environment variables set"

# STEP 7 - Deploy Function App
echo ""
echo "Step 7: Deploying Function App..."
func azure functionapp publish $FUNCTION_APP_NAME --python
echo "Done: Function App deployed!"

# COMPLETE
echo ""
echo "==================================================="
echo "Phase 20 Deployment Complete!"
echo "==================================================="
echo ""
echo "API Endpoint:"
echo "   https://$FUNCTION_APP_NAME.azurewebsites.net/api/grade"
echo ""
echo "Health Check:"
echo "   https://$FUNCTION_APP_NAME.azurewebsites.net/api/health"
echo ""
echo "Next: Add your API endpoint to dashboard.js!"