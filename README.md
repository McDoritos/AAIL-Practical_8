# CI/CD Pipeline for ML Systems - Tutorial

This tutorial explains a complete CI/CD pipeline that automatically tests, builds, trains, and deploys machine learning models to production using GitHub Actions.

---

## Pipeline Overview

The pipeline is split into **4 independent workflows** that run sequentially:

```
Workflow 1: Continuous Integration (CI)
├─ Unit Tests       → Verify code correctness
└─ Build Images     → Create Docker containers (training + serving)
         ↓
Workflow 2: Continuous Delivery (CD)
├─ Train Model      → Run training, select best model
├─ E2E Tests        → Validate serving + model integration
└─ Promote          → Tag as "staging" (image + model)
         ↓
Workflow 3: Continuous Staging
├─ Stage Tests      → Validate staging environment
└─ Promote          → Tag as "production" (image + model)
         ↓
Workflow 4: Continuous Deployment
└─ Deploy Prod      → Run production container
```

**Location**: `.github/workflows/`

---

## Why Separate Workflows?

### The Design Choice

Instead of one monolithic workflow, we use **4 chained workflows**. Each triggers the next via `workflow_run` events.

### Benefits of This Separation

1. **Modularity**: Each workflow has a clear, single responsibility
2. **Reusability**: Run workflows independently via `workflow_dispatch`
3. **Failure isolation**: Easy to identify which stage failed
4. **Testing**: Test staging/deployment separately without running CI
5. **Visibility**: GitHub Actions UI shows 4 clear stages

### Trade-offs

**Pros**:
- Clean separation of concerns (CI ≠ CD ≠ Staging ≠ Deployment)
- Can manually trigger any stage for debugging
- Easier to add environment-specific configurations

**Cons**:
- More files to maintain
- Slight overhead in workflow chaining (~10-20 seconds between stages)
- Need to pass artifacts through container registry

### Alternative Approaches

**Option A: Single Monolithic Workflow**
- All stages in one `.github/workflows/pipeline.yml`
- Jobs depend on each other using `needs: [job-name]`
- ✅ Simple, single file
- ❌ Hard to run individual stages, less flexible

**Option B: Environment-Based Separation**
- One workflow per environment: `ci.yml`, `staging.yml`, `production.yml`
- Triggered by branch or tag (e.g., `main` → staging, `v*` tags → production)
- ✅ Clear environment boundaries
- ❌ Doesn't separate CI concerns (test/build/train)

**Option C: Event-Based Separation**
- Split by trigger: `on-push.yml`, `on-pr.yml`, `on-release.yml`
- ✅ Different behavior per event type
- ❌ Duplicates pipeline logic

**Why We Chose Our Approach**: Best balance for learning ML pipelines. Shows progression: code validation → model creation → staged testing → deployment.

---

## Setting Up GitHub Actions

### Required Repository Settings

#### 1. Enable GitHub Actions
- Go to **Settings** → **Actions** → **General**
- Set **Workflow permissions** to "Read and write permissions"
- Check ✅ "Allow GitHub Actions to create and approve pull requests"

#### 2. Configure Environment Variables

Go to **Settings** → **Secrets and variables** → **Actions** → **Variables** tab:

| Variable Name | Example Value | Description |
|--------------|---------------|-------------|
| `REGISTRY` | `ghcr.io` | Container registry (GitHub Container Registry) |
| `MLFLOW_TRACKING_URI` | `http://your-mlflow.com:8080` | MLflow tracking server URL |
| `MLFLOW_EXPERIMENT_NAME` | `iris-classification` | Name of MLflow experiment |
| `MLFLOW_MODEL_NAME` | `iris-model` | Registered model name in MLflow |

#### 3. Configure Secrets

Go to **Settings** → **Secrets and variables** → **Actions** → **Secrets** tab:

| Secret Name | Value | Description |
|------------|-------|-------------|
| `MLFLOW_USERNAME` | Your MLflow username | Auth for MLflow tracking server |
| `MLFLOW_PASSWORD` | Your MLflow password | Auth for MLflow tracking server |

**Note**: `GITHUB_TOKEN` is automatically provided by GitHub Actions - no setup needed!

#### 4. Enable GitHub Container Registry (GHCR)

- Go to your **Profile** → **Settings** → **Developer settings** → **Personal access tokens** → **Tokens (classic)**
- Ensure your repository has package write permissions (automatic with `GITHUB_TOKEN`)
- Make packages public: **Package settings** → **Change visibility** → Public

### Testing Your Setup

After configuration, trigger manually:

1. Go to **Actions** tab
2. Select **"1 - Continuous Integration"**
3. Click **"Run workflow"** → **"Run workflow"**
4. Watch it execute! Should complete without errors.

---

## Workflow 1: Continuous Integration

**File**: `.github/workflows/1_continuous_integration.yml`

**Trigger**: Runs on every push or pull request to `main` branch

**Purpose**: Validate code quality and build container images

### Workflow Configuration

```yaml
on:
  push:
    branches: [ main ]
  pull_request:
    branches: [ main ]
  workflow_dispatch:  # Manual trigger
```

- Runs on all changes to `main`
- Also runs on PRs targeting `main` (validate before merge)
- Can be manually triggered from GitHub UI

### Job 1: `test-unit`

**What it does**: Run fast unit tests to validate code correctness

```yaml
- uses: actions/setup-python@v5
  with: { python-version: '3.13' }
- run: pip install uv
- run: uv sync
- run: uv run pytest tests/test_api.py -v
- run: uv run pytest tests/test_train.py -v
```

**Steps**:
1. Setup Python 3.13 environment
2. Install `uv` (fast Python package manager)
3. Install dependencies from `pyproject.toml`
4. Run API unit tests (Flask endpoints, input validation)
5. Run training unit tests (model creation, data processing)

**Why separate test files?** Easier to identify if API or training logic broke.

**If fails**: Pipeline stops. Fix tests before building images.

---

### Job 2: `build-images`

**What it does**: Build Docker images for training and serving

**Depends on**: `test-unit` (only runs if tests pass)

```yaml
needs: test-unit
```

#### Step 2a: Build Training Image

```yaml
- uses: docker/build-push-action@v5
  with:
    context: .
    file: ./training/Dockerfile
    platforms: linux/amd64
    push: false
    tags: training:${{ github.sha }}
    outputs: type=docker,dest=/tmp/training.tar
```

**Key details**:
- `context: .` - Build from project root
- `file: ./training/Dockerfile` - Use training-specific Dockerfile
- `platforms: linux/amd64` - Build for Intel/AMD (GitHub runners)
- `push: false` - Don't push yet, validate first
- `tags: training:${{ github.sha }}` - Tag with commit hash (traceability)
- `outputs: type=docker,dest=/tmp/training.tar` - Save to file

#### Step 2b: Build Serving Image

```yaml
- uses: docker/build-push-action@v5
  with:
    context: .
    file: ./serving/Dockerfile.flask
    platforms: linux/amd64
    push: false
    tags: serving:${{ github.sha }}
    outputs: type=docker,dest=/tmp/serving.tar
```

Same approach, different Dockerfile. Serving image contains Flask app + model loading logic.

#### Step 2c: Push to Registry

```yaml
- uses: docker/login-action@v3
  with:
    registry: ${{ env.REGISTRY }}
    username: ${{ github.actor }}
    password: ${{ secrets.GITHUB_TOKEN }}

- run: |
    docker tag training:${{ github.sha }} ${{ env.REGISTRY }}/${{ github.repository }}/training:${{ github.sha }}
    docker push ${{ env.REGISTRY }}/${{ github.repository }}/training:${{ github.sha }}

- run: |
    docker tag serving:${{ github.sha }} ${{ env.REGISTRY }}/${{ github.repository }}/serving:${{ github.sha }}
    docker push ${{ env.REGISTRY }}/${{ github.repository }}/serving:${{ github.sha }}
```

**Why push now?**
- Makes images available to next workflow
- GitHub Container Registry (GHCR) acts as artifact storage
- Alternative: Use `actions/upload-artifact` (but limited to 10GB, slower for large images)

**Environment variables used**:
- `REGISTRY`: `ghcr.io`
- `github.repository`: `your-username/your-repo-name`
- `github.sha`: Git commit hash

**If fails**: Check Dockerfile syntax, missing files, or registry permissions

---

## Workflow 2: Continuous Delivery

**File**: `.github/workflows/2_continuous_delivery.yml`

**Trigger**: Automatically runs when Workflow 1 completes successfully

**Purpose**: Train model, validate with E2E tests, promote to staging

### Workflow Configuration

```yaml
on:
  workflow_run:
    workflows: ["1 - Continuous Integration"]
    types: [completed]
  workflow_dispatch:
```

- `workflow_run`: Chained trigger (waits for CI to finish)
- Only proceeds if CI succeeded: `if: ${{ github.event.workflow_run.conclusion == 'success' }}`

### Job 1: `train-model`

**What it does**: Run training pipeline, select best model, run E2E tests, promote to staging

#### Step 1a: Run Training

```yaml
- run: docker pull ${{ env.REGISTRY }}/${{ github.repository }}/training:${{ github.sha }}

- run: |
    docker run --rm \
      -e MLFLOW_TRACKING_URI \
      -e MLFLOW_TRACKING_USERNAME \
      -e MLFLOW_TRACKING_PASSWORD \
      -e MLFLOW_MODEL_NAME \
      -e MLFLOW_EXPERIMENT_NAME \
      -e COMMIT_SHA \
      ${{ env.REGISTRY }}/${{ github.repository }}/training:${{ github.sha }}
```

**What happens inside the container**:
1. Loads Iris dataset
2. Trains multiple models with different hyperparameters (C=0.1, 1.0, 10.0)
3. Logs metrics (accuracy, precision, recall) to MLflow
4. Selects best model based on accuracy
5. Registers model in MLflow Model Registry
6. Sets alias: `<commit-sha>` pointing to best model

**Environment variables passed**:
- `MLFLOW_TRACKING_URI`: Where MLflow server is hosted
- `MLFLOW_TRACKING_USERNAME/PASSWORD`: Authentication
- `MLFLOW_MODEL_NAME`: Name to register model under
- `MLFLOW_EXPERIMENT_NAME`: Experiment to log runs to
- `COMMIT_SHA`: Used to tag model version

#### Step 1b: Test Serving with New Model

```yaml
- run: docker pull ${{ env.REGISTRY }}/${{ github.repository }}/serving:${{ github.sha }}

- run: |
    docker run -d \
      --name serving-app \
      -p 8080:8080 \
      -e MLFLOW_TRACKING_URI \
      -e MLFLOW_TRACKING_USERNAME \
      -e MLFLOW_TRACKING_PASSWORD \
      -e MODEL_ALIAS=${{ github.sha }} \
      -e MLFLOW_MODEL_NAME \
      ${{ env.REGISTRY }}/${{ github.repository }}/serving:${{ github.sha }}
    sleep 10

- run: uv run pytest tests/test_e2e.py -v
```

**E2E Test Coverage** (`tests/test_e2e.py`):
1. Health check: `GET /health` returns 200
2. Prediction endpoint: `POST /predict` with valid data
3. Error handling: Invalid input returns proper error
4. Model loading: Verifies model loaded from MLflow

**Why test here?** Validate that:
- Serving image correctly loads model from MLflow
- Model inference works end-to-end
- API endpoints respond correctly

#### Step 1c: Promote to Staging

```yaml
- run: |
    docker tag ${{ env.REGISTRY }}/${{ github.repository }}/serving:${{ github.sha }} \
               ${{ env.REGISTRY }}/${{ github.repository }}/serving:staging
    docker push ${{ env.REGISTRY }}/${{ github.repository }}/serving:staging

- run: uv run python model-promotion/promote_model.py
  env:
    FROM_ALIAS: ${{ github.sha }}
    TO_ALIAS: staging
```

**What happens**:
1. Tag Docker image with `staging` label
2. Push to registry (makes `serving:staging` available)
3. Run promotion script:
   - Finds model with alias `<commit-sha>`
   - Adds alias `staging` to same model version
   - Now model has two aliases: `<commit-sha>` and `staging`

**Why aliases?** MLflow aliases let you point to specific model versions without hardcoding version numbers.

**If fails**: Check MLflow connectivity, model not found, or E2E tests failed

---

## Workflow 3: Continuous Staging

**File**: `.github/workflows/3_continuous_staging.yml`

**Trigger**: Automatically runs when Workflow 2 completes successfully

**Purpose**: Validate staging environment, promote to production

### Workflow Configuration

```yaml
on:
  workflow_run:
    workflows: ["2 - Continuous Delivery"]
    types: [completed]
```

### Job 1: `stage-tests`

**What it does**: Test staging artifacts, promote to production if tests pass

#### Step 1a: Test Staging Image

```yaml
- run: docker pull ${{ env.REGISTRY }}/${{ github.repository }}/serving:staging

- run: |
    docker run -d \
      --name serving-app \
      -p 8080:8080 \
      -e MODEL_ALIAS=${{ github.sha }} \
      ${{ env.REGISTRY }}/${{ github.repository }}/serving:staging
    sleep 10

- run: uv run pytest tests/test_e2e.py -v
```

**Key difference from CD workflow**: Uses `serving:staging` image instead of `serving:<commit-sha>`

**Why test again?** Validates:
- The `staging` tag points to correct image
- No issues in tagging/promotion process
- Same tests in staging environment

**IMPORTANT: In production systems, this stage would**:
- Deploy to staging environment (separate infrastructure)
- Run extended test suite (performance, load, security tests)
- A/B testing with shadow traffic
- Manual QA validation
- Wait for approval before production

#### Step 1b: Promote to Production

```yaml
- run: uv run python model-promotion/promote_model.py
  env:
    FROM_ALIAS: staging
    TO_ALIAS: production

- run: |
    docker tag ${{ env.REGISTRY }}/${{ github.repository }}/serving:staging \
               ${{ env.REGISTRY }}/${{ github.repository }}/serving:production
    docker push ${{ env.REGISTRY }}/${{ github.repository }}/serving:production
```

**What happens**:
1. Promote model: Add `production` alias to model (keeps `staging` alias too)
2. Tag Docker image with `production`
3. Push to registry

**Result**: Both model and container are now production-ready

**If fails**: Staging tests failed, review logs before promoting

---

## Workflow 4: Continuous Deployment

**File**: `.github/workflows/4_continuous_deployment.yml`

**Trigger**: Automatically runs when Workflow 3 completes successfully

**Purpose**: Deploy production container

### Workflow Configuration

```yaml
on:
  workflow_run:
    workflows: ["3 - Continuous Staging"]
    types: [completed]
```

### Job 1: `deploy-prod`

**What it does**: Pull production image and run it

```yaml
- uses: docker/login-action@v3
- run: docker pull ${{ env.REGISTRY }}/${{ github.repository }}/serving:production
- run: docker stop serving-app || true
- run: docker rm serving-app || true

- run: |
    docker run -d --name serving-app -p 9000:8080 \
      -e MLFLOW_TRACKING_URI \
      -e MLFLOW_TRACKING_USERNAME \
      -e MLFLOW_TRACKING_PASSWORD \
      -e MODEL_ALIAS=${{ github.sha }} \
      -e MLFLOW_MODEL_NAME \
      ${{ env.REGISTRY }}/${{ github.repository }}/serving:production
```

**Key details**:
- Port mapping: `9000:8080` (expose on port 9000 to avoid conflicts)
- Stop/remove old container before starting new one
- Uses `production` tagged image

**Limitations of this approach** (simplified for learning):
- Deploys to same GitHub runner (not a real server)
- Brief downtime during container swap
- No health checks before switching traffic

**Real-world deployment patterns**:

1. **SSH to remote server**:
```yaml
- uses: appleboy/ssh-action@master
  with:
    host: ${{ secrets.PROD_HOST }}
    username: ${{ secrets.PROD_USER }}
    key: ${{ secrets.SSH_KEY }}
    script: |
      docker pull registry/image:production
      docker-compose up -d
```

**If fails**: Check deployment target availability, credentials, or resource limits

---

## Key Concepts

### 1. Workflow Chaining

```yaml
on:
  workflow_run:
    workflows: ["1 - Continuous Integration"]
    types: [completed]

jobs:
  train-model:
    if: ${{ github.event.workflow_run.conclusion == 'success' }}
```

**How it works**:
- Workflow 2 waits for Workflow 1 to complete
- Only runs if previous workflow succeeded
- Creates sequential pipeline: CI → CD → Staging → Deployment

**Benefits**: Each workflow is independent, can be triggered manually

### 2. Artifact Passing via Registry

Instead of GitHub Actions artifacts, we use the container registry:

```
Workflow 1: Build → Push to ghcr.io/repo/image:abc123
Workflow 2: Pull from ghcr.io/repo/image:abc123 → Test
```

**Why?**
- No 10GB artifact size limit
- Images available outside GitHub Actions
- Natural for container-based deployments

### 3. Image Tagging Strategy

```
serving:abc123def       → Specific commit (immutable)
serving:staging         → Latest validated in CD (moves)
serving:production      → Latest deployed (moves)
```

**Traceability**: Can always rollback to specific commit SHA

### 4. MLflow Aliases

Similar to image tags, but for models:

```
Model Version 5:
  - alias: abc123def (commit)
  - alias: staging
  - alias: production
```

**Benefits**:
- Serving app loads `model:production` (no version numbers)
- Promotion = adding alias (no model copying)
- Version history preserved

### 5. Environment Variables vs Secrets

**Variables** (public, in Variables tab):
- `REGISTRY`: ghcr.io
- `MLFLOW_TRACKING_URI`: http://mlflow.example.com
- `MLFLOW_MODEL_NAME`: iris-model

**Secrets** (encrypted, in Secrets tab):
- `MLFLOW_USERNAME`: admin
- `MLFLOW_PASSWORD`: •••••••

**Rule**: If it's sensitive (passwords, keys), use secrets!

### 6. Manual Triggers

All workflows have `workflow_dispatch`:

```yaml
on:
  workflow_run: ...
  workflow_dispatch:  # Enables manual triggering
```

**Use cases**:
- Test deployment without running full pipeline
- Rollback by re-running old workflow
- Debug specific stage

---

## Exercise 1: Deploy and Explore the Pipeline

### Objective

Get hands-on experience with the complete ML pipeline by deploying it in your own repository and exploring all the components.

### Part 1: Setup and First Deployment

#### Step 1: Fork and Configure Repository

1. **Fork this repository** to your GitHub account
2. **Clone your fork** locally:
   ```bash
   git clone https://github.com/YOUR-USERNAME/laia-tutorial.git
   cd laia-tutorial
   ```

3. **Configure GitHub Actions** (follow [Setting Up GitHub Actions](#setting-up-github-actions)):
   - Enable GitHub Actions with read/write permissions
   - Add repository variables: `REGISTRY`, `MLFLOW_TRACKING_URI`, `MLFLOW_EXPERIMENT_NAME`, `MLFLOW_MODEL_NAME`
   - Add secrets: `MLFLOW_USERNAME`, `MLFLOW_PASSWORD`

#### Step 2: Trigger Your First Pipeline Run

1. Go to your repository's **Actions** tab
2. Select **"1 - Continuous Integration"**
3. Click **"Run workflow"** → **"Run workflow"**
4. Watch the pipeline execute through all 4 workflows

**What to observe**:
- ✅ Unit tests passing
- ✅ Docker images being built
- ✅ Training completing with 3 models
- ✅ E2E tests validating the serving API
- ✅ Promotion through staging to production

### Part 2: Explore Docker Images in GitHub Container Registry

#### Step 3: View Your Container Images

1. Go to your GitHub profile
2. Click on **"Packages"** tab
3. You should see two packages:
   - `laia-tutorial/training`
   - `laia-tutorial/serving`

**Questions to answer**:
- How many tags does each image have? (Hint: commit SHA, staging, production)
- What is the size of each image?
- Which image is larger and why?

#### Step 4: Inspect Image Tags

Click on the `serving` package and examine the tags:

```
serving:abc123def456...  (commit SHA - immutable)
serving:staging          (latest validated)
serving:production       (currently deployed)
```

**Exercise**: Find which commit SHA is currently tagged as `production`. Does it match the latest commit?

### Part 3: Analyze Models in MLflow

#### Step 5: Explore MLflow UI

1. Open your MLflow server: `MLFLOW_TRACKING_URI`
2. Navigate to **Experiments** → Select your experiment

**What to explore**:
- How many runs were created by your pipeline?
- Compare metrics across the 3 runs (C=0.1, C=1.0, C=10.0)
- Which hyperparameter value performed best?

#### Step 6: Examine Model Registry

1. In MLflow, go to **Models** tab
2. Click on your model (e.g., `iris-model`)
3. View the **Versions** and **Aliases**

**Questions to answer**:
- Which version is currently in production?
- What aliases are assigned to the latest version?
- What was the accuracy of the production model?

#### Step 7: Analyze Model Artifacts

1. Click on a model version
2. Navigate to the source run
3. Explore the **Artifacts** section

**What to find**:
- Trained model file (`model.pkl` or similar)
- Model visualization (`results_C*.png`)
- Confusion matrix or other metrics visualizations

### Part 4: Make a Change and Redeploy

#### Step 8: Modify Training Parameters

1. Open `training/train_model.py`
2. Modify the hyperparameter grid to test different values:
   ```python
   # Change from:
   C_values = [0.1, 1.0, 10.0]
   
   # To:
   C_values = [0.5, 5.0, 50.0]
   ```

3. Commit and push:
   ```bash
   git add training/train_model.py
   git commit -m "Test new hyperparameters"
   git push origin main
   ```

#### Step 9: Monitor the Automatic Deployment

1. Watch the **Actions** tab. The pipeline should trigger automatically
2. Observe the new models being trained
3. Check MLflow - you should see 3 new runs with your new C values

#### Step 10: Verify the Updated Model is Live

After the pipeline completes:

1. Check MLflow Model Registry - verify the new version has the `production` alias
2. Check GHCR - verify the `production` tag points to your latest commit

### Reflection Questions

1. **Traceability**: How can you identify which code version produced which model?
2. **Rollback**: If the new model is worse, how would you rollback to the previous version?
3. **Automation vs Control**: The pipeline automatically deploys to production. Is this safe? What's missing?

---

## Exercise 2: Implement Model Quality Gates

### The Problem

Currently, **every trained model automatically gets promoted to staging** - even if it performs poorly! In production ML systems, this is dangerous. You need quality gates that validate model performance before allowing promotion.

### Your Task

Implement a model quality validation step that:

1. **Runs after training** but **before E2E tests**
2. **Retrieves the trained model's metrics** from MLflow (accuracy, precision, recall)
3. **Checks quality thresholds**:
   - Minimum accuracy: 0.90
   - Minimum precision: 0.85
4. **Stops the pipeline** if quality checks fail (exit code 1)
5. **Allows promotion** if quality checks pass (exit code 0)

### Where to Implement

**Location**: Between Step 1a (Run Training) and Step 1b (Test Serving) in Workflow 2

**Files you'll need to create/modify**:
- `model-validation/validate_quality.py` - Python script to check model quality
- `.github/workflows/2_continuous_delivery.yml` - Add validation step

### Hints

<details>
<summary>💡 How to retrieve model metrics from MLflow</summary>

```python
import mlflow

# Connect to MLflow
mlflow.set_tracking_uri(os.getenv("MLFLOW_TRACKING_URI"))

# Get the model version by alias
client = mlflow.MlflowClient()
model_versions = client.get_model_version_by_alias(
    name=os.getenv("MLFLOW_MODEL_NAME"),
    alias=os.getenv("MODEL_ALIAS")  # Will be the commit SHA
)

# Get the run that created this model version
run_id = model_versions.run_id
run = client.get_run(run_id)

# Access metrics
accuracy = run.data.metrics.get("accuracy")
```
</details>

<details>
<summary>💡 How to fail the pipeline</summary>

In Python:
```python
import sys
sys.exit(1)  # Non-zero exit code fails the workflow
```

In your workflow YAML:
```yaml
- name: Validate Model Quality
  run: uv run python model-validation/validate_quality.py
  # If the script exits with code 1, the workflow stops here
```
</details>

<details>
<summary>💡 Expected behavior</summary>

**When model is good** (accuracy ≥ 0.90, precision ≥ 0.85):
```
✅ Model passed quality gate
   - Accuracy: 0.95 (threshold: 0.90)
   - Precision: 0.93 (threshold: 0.85)
```
→ Pipeline continues to E2E tests and promotion

**When model is poor**:
```
❌ Model FAILED quality gate
   - Accuracy: 0.85 (threshold: 0.90) ❌
   - Precision: 0.88 (threshold: 0.85) ✅
Pipeline stopped. Model will NOT be promoted.
```
→ Pipeline stops, no promotion to staging
</details>

### Testing Your Solution

1. **Test with good model**: Run the pipeline normally - should pass
2. **Test with bad model**: Modify thresholds temporarily to force failure
   ```python
   MIN_ACCURACY = 0.99  # Iris model won't reach this
   ```
3. **Verify pipeline stops**: Check that E2E tests never run when validation fails

### Why This Matters

In production ML systems:
- **Prevents bad models** from reaching users
- **Enforces quality standards** across team
- **Catches training bugs** (data issues, code bugs)
- **Enables safe automation** - pipeline can run without human approval

This is a critical component of **MLOps best practices**!

---

## Complete Pipeline Flow

```
Push to main
     ↓
┌──────────────────────────────────────────────┐
│ Workflow 1: Continuous Integration           │
│ ├─ test-unit (30-45s)                        │
│ └─ build-images (2-4 min)                    │
│    ├─ Build training image                   │
│    ├─ Build serving image                    │
│    └─ Push to ghcr.io                        │
└──────────────────────────────────────────────┘
     ↓ (on success)
┌──────────────────────────────────────────────┐
│ Workflow 2: Continuous Delivery              │
│ └─ train-model (3-4 min)                     │
│    ├─ Run training (trains 3 models)         │
│    ├─ Register best model → MLflow           │
│    ├─ E2E tests with new model               │
│    └─ Promote to staging (image + model)     │
└──────────────────────────────────────────────┘
     ↓ (on success)
┌──────────────────────────────────────────────┐
│ Workflow 3: Continuous Staging               │
│ └─ stage-tests (1-2 min)                     │
│    ├─ Pull serving:staging image             │
│    ├─ Run staging validation tests           │
│    └─ Promote to production (image + model)  │
└──────────────────────────────────────────────┘
     ↓ (on success)
┌──────────────────────────────────────────────┐
│ Workflow 4: Continuous Deployment            │
│ └─ deploy-prod (30s)                         │
│    ├─ Pull serving:production image          │
│    └─ Deploy to production                   │
└──────────────────────────────────────────────┘
     ↓
✅ Production Deployed!
```
