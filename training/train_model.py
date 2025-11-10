"""CI-friendly training script for GitHub Actions."""
import os
import mlflow
from sklearn.datasets import load_iris
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score
import matplotlib
matplotlib.use('Agg')  # Use non-interactive backend for CI
import matplotlib.pyplot as plt

COMMIT_SHA = os.getenv('COMMIT_SHA')
if not COMMIT_SHA:
    raise EnvironmentError("Missing required env var: COMMIT_SHA")

MODEL_NAME = os.getenv('MLFLOW_MODEL_NAME')
if not MODEL_NAME:
    raise EnvironmentError("Missing required env var: MLFLOW_MODEL_NAME")

EXP_NAME = os.getenv('MLFLOW_EXPERIMENT_NAME')
if not EXP_NAME:
    raise EnvironmentError("Missing required env var: MLFLOW_EXPERIMENT_NAME")

def train_model():
    """Train iris classification model and log to MLflow."""
    # Configure MLflow to use local server
    mlflow_uri = os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5050")
    mlflow.set_tracking_uri(mlflow_uri)
    
    # Set experiment
    mlflow.set_experiment(EXP_NAME)
    
    # Load data
    X, y = load_iris(return_X_y=True)
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.3, random_state=42
    )
    
    best_acc = 0
    best_run_id = None
    best_C = None
    
    # Train models with different C values
    for C in [0.1, 1.0, 10.0]:
        with mlflow.start_run() as run:
            print(f"Training model with C={C}")
            model = LogisticRegression(max_iter=200, C=C)
            model.fit(X_train, y_train)
            preds = model.predict(X_test)
            acc = accuracy_score(y_test, preds)
            
            print(f"  Accuracy: {acc:.4f}")
            
            # Log parameters and metrics
            mlflow.log_param("C", C)
            mlflow.log_metric("accuracy", acc)
            
            # Create and log figure
            fig, ax = plt.subplots(figsize=(8, 6))
            ax.scatter(y_test, preds)
            ax.set_xlabel("True")
            ax.set_ylabel("Predicted")
            ax.set_title(f"C={C}, Accuracy={acc:.4f}")
            mlflow.log_figure(fig, f"results_C{C}.png")
            plt.close(fig)
            
            # Infer model signature
            signature = mlflow.models.infer_signature(
                X_train, model.predict(X_train)
            )
            
            # Log model
            mlflow.sklearn.log_model(
                model,
                name="model",
                signature=signature,
                input_example=X_train[:5]
            )
            
            # Track the best model
            if acc > best_acc:
                best_acc = acc
                best_run_id = run.info.run_id
                best_C = C
    
    # Register the best model
    print(f"\nBest model: C={best_C}, accuracy={best_acc:.4f}")
    print(f"Best run ID: {best_run_id}")
    
    model_uri = f"runs:/{best_run_id}/model"
    
    try:
        registered_model = mlflow.register_model(model_uri, MODEL_NAME)
        print(f"Registered model version: {registered_model.version}")
        
        # Promote to Production (required for Flask app to load it)
        from mlflow.tracking import MlflowClient
        # Assign alias (e.g., production)
        client = MlflowClient()
        client.set_registered_model_alias(
            name=MODEL_NAME,
            alias="staging",  # or "staging", "canary", etc.
            version=registered_model.version,
        )

        # Create alias for commit SHA (truncate for readability)
        client.set_registered_model_alias(
            name=MODEL_NAME,
            alias=COMMIT_SHA,
            version=registered_model.version,
        )

        print(f"✓ Model version {registered_model.version} promoted to Production")
        
    except Exception as e:
        print(f"ERROR: Failed to register/promote model: {e}")
        print(f"Model URI: {model_uri}")
        print(f"MLflow tracking URI: {os.getenv('MLFLOW_TRACKING_URI')}")
        raise  # Re-raise to fail the CI pipeline if registration fails
    
    return best_run_id, best_acc


if __name__ == "__main__":
    print("Starting CI model training...")
    run_id, accuracy = train_model()
    print(f"\nTraining complete!")
    print(f"Best run ID: {run_id}")
    print(f"Best accuracy: {accuracy:.4f}")
    
    # Verify minimum accuracy threshold
    assert accuracy > 0.85, f"Model accuracy {accuracy:.4f} is below threshold 0.85"
    print("✓ Model meets accuracy requirements")

