# Azure Setup Guide for Tutorial Pipeline (RBAC / Keyless)

This guide walks you through setting up the two Azure services the pipeline
needs, assigning RBAC roles, logging in, and running your first tutorial.

---

## What You Need

The pipeline uses **two** Azure AI services:

| Service | Purpose | Required |
|---|---|---|
| **Azure OpenAI** | Generates the tutorial script (Stage 1) | Yes |
| **Azure Speech** | Synthesises the voice-over (Stage 2 primary) | Yes |

Both authenticate with your Azure AD identity — no API keys.

---

## Step 1: Find or Create an Azure OpenAI Resource

1. Go to the [Azure Portal](https://portal.azure.com).
2. Search for **"Azure OpenAI"** in the top search bar.
3. If you already have an Azure OpenAI resource, click it and skip to
   step 5.
4. If not, click **+ Create** and fill in:
   - **Subscription**: your subscription
   - **Resource group**: pick an existing one or create a new one
     (e.g. `rg-tutorials`)
   - **Region**: choose a region that supports GPT-4.1
     (East US, East US 2, Sweden Central, or West US 3 are common)
   - **Name**: e.g. `oai-tutorials`
   - **Pricing tier**: Standard S0
   - Click **Review + Create** → **Create**.
5. Once created, open the resource and note the **Endpoint** from the
   **Overview** pane (looks like
   `https://oai-tutorials.openai.azure.com/`).

### Deploy a Model

6. In the Azure OpenAI resource, go to **Model deployments** →
   **Manage Deployments** (opens Azure AI Foundry).
7. Click **+ Deploy model** → **Deploy base model**.
8. Select **gpt-4.1** (or **gpt-4o** if 4.1 is not available in your
   region).
9. Set a **Deployment name** — e.g. `gpt-4.1`. Note this name exactly.
10. Set rate limit as needed, click **Deploy**.

---

## Step 2: Find or Create an Azure Speech Resource

1. In the Azure Portal, search for **"Speech"** (under Cognitive
   Services / AI Services).
2. If you already have a Speech resource, click it and skip to step 4.
3. If not, click **+ Create** and fill in:
   - **Subscription**: your subscription
   - **Resource group**: same as above (e.g. `rg-tutorials`)
   - **Region**: pick any region (e.g. `eastus`)
   - **Name**: e.g. `speech-tutorials`
   - **Pricing tier**: Free F0 (or Standard S0)
   - Click **Review + Create** → **Create**.
4. Once created, open the resource and note the **Region** from the
   **Overview** pane (e.g. `eastus`).

---

## Step 3: Assign RBAC Roles to Your Identity

You need two role assignments — one on each resource.

### On the Azure OpenAI resource

1. Open your Azure OpenAI resource in the portal.
2. Go to **Access control (IAM)** in the left menu.
3. Click **+ Add** → **Add role assignment**.
4. In the **Role** tab, search for **Cognitive Services OpenAI User**
   and select it. Click **Next**.
5. In the **Members** tab:
   - **Assign access to**: User, group, or service principal
   - Click **+ Select members**, find your name/email, select it.
6. Click **Review + assign** → **Review + assign**.

### On the Azure Speech resource

1. Open your Azure Speech resource in the portal.
2. Go to **Access control (IAM)**.
3. Click **+ Add** → **Add role assignment**.
4. Search for **Cognitive Services Speech User** and select it.
   Click **Next**.
5. Select yourself as the member (same as above).
6. Click **Review + assign** → **Review + assign**.

> **Note**: Role assignments can take up to 5 minutes to propagate.

---

## Step 4: Install Azure CLI and Log In

The pipeline uses `DefaultAzureCredential` which needs you to be logged
in. The easiest method is via Azure CLI.

### Install Azure CLI

Open a **new** terminal **as Administrator** and run:

```powershell
winget install -e --id Microsoft.AzureCLI
```

After installation, **close and reopen** your terminal so `az` is on
your PATH.

### Log in

```powershell
az login
```

This opens a browser window. Sign in with your Microsoft account.
After login, verify:

```powershell
az account show --query "{name:name, id:id}" -o table
```

If you have multiple subscriptions, select the one containing your
resources:

```powershell
az account set --subscription "YOUR_SUBSCRIPTION_NAME_OR_ID"
```

> **Alternative (no Azure CLI)**: If you cannot install Azure CLI, the
> pipeline will fall back to `InteractiveBrowserCredential` and open a
> browser window for login on first run.

---

## Step 5: Set Environment Variables

Open a terminal in the `tutorials/` folder and set these variables:

```powershell
$env:AZURE_OPENAI_ENDPOINT = "https://YOUR-RESOURCE-NAME.openai.azure.com/"
$env:AZURE_SPEECH_REGION = "eastus"
```

Replace:

- `YOUR-RESOURCE-NAME` with your Azure OpenAI resource name from Step 1
  (e.g. `oai-tutorials`)
- `eastus` with your Speech resource region from Step 2

> These values are **not secrets** — they are just resource identifiers.

---

## Step 6: Update the Pipeline Config (If Needed)

The deployment name in `config/pipeline.yaml` must match the deployment
you created in Step 1:

```yaml
script:
  provider: azure_openai
  model: gpt-4.1          # ← must match your deployment name exactly
```

If you deployed a different model name (e.g. `gpt-4o`), update this
value.

---

## Step 7: Run the Pipeline

```powershell
cd c:\Users\otudusciuc\work\tutorials
uv run python main.py "what are harnesses and how to use them" --verbose
```

### What to expect

1. **First run**: if using `InteractiveBrowserCredential`, a browser
   window opens for Azure login. Subsequent runs use the cached token.
2. **Stage 1**: Script generation via Azure OpenAI (~10-30 seconds).
3. **Stage 2**: Voice synthesis via Azure Speech (~10-20 seconds).
4. **Stage 3**: Screen recording via Playwright (requires Playwright
   setup — may fail on first run, see troubleshooting).
5. **Stage 4-5**: Post-production and publishing.

---

## Troubleshooting

### "AZURE_OPENAI_ENDPOINT environment variable not set"

Run the `$env:AZURE_OPENAI_ENDPOINT = ...` command from Step 5 in your
current terminal session.

### "DefaultAzureCredential failed to retrieve a token"

- Verify you ran `az login` and it succeeded.
- Verify the RBAC role assignments from Step 3 have propagated
  (wait 5 minutes).
- Check you are using the correct subscription:
  `az account show -o table`.

### "AuthorizationFailed" or "403 Forbidden"

- The RBAC role is not assigned or has not propagated yet.
- Verify the role name is exactly **Cognitive Services OpenAI User**
  (not "Contributor" or "Reader").

### "DeploymentNotFound" or model errors

- The `model` value in `config/pipeline.yaml` must exactly match your
  Azure OpenAI deployment name (not the model name).
- Check your deployment in the Azure Portal → Azure OpenAI →
  Model deployments.

### Playwright errors on Stage 3

This is expected if Playwright browsers are not installed:

```powershell
npx playwright install chromium
```

---

## Quick Reference

| Variable | Example Value | Where to Find |
|---|---|---|
| `AZURE_OPENAI_ENDPOINT` | `https://oai-tutorials.openai.azure.com/` | Azure Portal → Azure OpenAI → Overview |
| `AZURE_SPEECH_REGION` | `eastus` | Azure Portal → Speech resource → Overview |
| deployment name | `gpt-4.1` | Azure Portal → Azure OpenAI → Model deployments |
