"""MLflow autolog setup for LangGraph/LangChain tracing.

Import this module once at application startup to enable automatic tracing
of all LangChain/LangGraph operations (LLM calls, tool invocations, agent
decisions) with zero changes to agent code.
"""

import logging
import os

logger = logging.getLogger(__name__)

_mlflow_enabled = False


def init_mlflow():
    """Initialize MLflow tracing if MLFLOW_TRACKING_URI is configured."""
    global _mlflow_enabled

    tracking_uri = os.getenv("MLFLOW_TRACKING_URI", "")
    if not tracking_uri:
        logger.info("MLFLOW_TRACKING_URI not set — MLflow tracing disabled")
        return

    try:
        import mlflow
        import mlflow.langchain

        mlflow.set_tracking_uri(tracking_uri)
        mlflow.set_experiment(
            os.getenv("MLFLOW_EXPERIMENT_NAME", "deep-research-harness")
        )
        mlflow.langchain.autolog()
        _mlflow_enabled = True
        logger.info("MLflow tracing enabled: %s", tracking_uri)
    except Exception as e:
        logger.warning("MLflow initialization failed (tracing disabled): %s", e)
