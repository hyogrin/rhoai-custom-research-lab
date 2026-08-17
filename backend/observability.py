"""MLflow autolog setup for LangGraph/LangChain tracing.

Import this module once at application startup to enable automatic tracing
of all LangChain/LangGraph operations (LLM calls, tool invocations, agent
decisions) with zero changes to agent code.
"""

import logging
import os

logger = logging.getLogger(__name__)

_mlflow_enabled = False


def _patch_tracer_for_langgraph():
    """Patch MlflowLangchainTracer for LangGraph compatibility.

    Fixes two issues:
    1. Missing ``on_interrupt`` / ``on_resume`` callbacks — LangGraph fires
       these but MLflow's tracer doesn't implement them, causing noisy
       ``AttributeError`` warnings in the callback manager.
    2. ``GraphInterrupt`` logged as error — ``interrupt()`` raises
       ``GraphInterrupt`` as normal HITL control flow, but MLflow's
       ``on_chain_error`` records it as a failed span with a full traceback.
    """
    try:
        from mlflow.langchain.langchain_tracer import MlflowLangchainTracer

        for attr in ("on_interrupt", "on_resume"):
            if not hasattr(MlflowLangchainTracer, attr):
                setattr(MlflowLangchainTracer, attr, lambda self, *a, **kw: None)
                logger.debug("Patched MlflowLangchainTracer.%s (no-op)", attr)

        _original_on_chain_error = getattr(MlflowLangchainTracer, "on_chain_error", None)
        _original_on_chain_end = getattr(MlflowLangchainTracer, "on_chain_end", None)
        if _original_on_chain_error and _original_on_chain_end:
            def _filtered_on_chain_error(self, error, *args, **kwargs):
                from langgraph.errors import GraphInterrupt
                if isinstance(error, GraphInterrupt):
                    _original_on_chain_end(
                        self, {"status": "interrupted"}, *args, **kwargs
                    )
                    return
                return _original_on_chain_error(self, error, *args, **kwargs)

            MlflowLangchainTracer.on_chain_error = _filtered_on_chain_error
            logger.debug("Patched MlflowLangchainTracer.on_chain_error (GraphInterrupt → on_chain_end)")
    except Exception:
        pass


def init_mlflow():
    """Initialize MLflow tracing if MLFLOW_TRACKING_URI is configured."""
    global _mlflow_enabled

    tracking_uri = os.getenv("MLFLOW_TRACKING_URI", "")
    if not tracking_uri:
        logger.info("MLFLOW_TRACKING_URI not set — MLflow tracing disabled")
        return

    if os.getenv("MLFLOW_TRACKING_INSECURE_TLS", "").lower() in ("true", "1", "yes"):
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    workspace = os.getenv("MLFLOW_WORKSPACE", "")
    if workspace and not os.getenv("MLFLOW_HTTP_REQUEST_HEADERS"):
        os.environ["MLFLOW_HTTP_REQUEST_HEADERS"] = (
            f'{{"x-mlflow-workspace": "{workspace}"}}'
        )

    try:
        import mlflow
        import mlflow.langchain
        import mlflow.openai

        mlflow.set_tracking_uri(tracking_uri)
        mlflow.set_experiment(
            os.getenv("MLFLOW_EXPERIMENT_NAME", "deep-research-harness")
        )
        mlflow.langchain.autolog(run_tracer_inline=True)
        mlflow.openai.autolog()

        _patch_tracer_for_langgraph()

        _mlflow_enabled = True
        logger.info("MLflow LangChain/LangGraph + OpenAI tracing enabled: %s", tracking_uri)
    except Exception as e:
        logger.warning("MLflow initialization failed (tracing disabled): %s", e)


def is_enabled() -> bool:
    """Return whether MLflow tracing is active."""
    return _mlflow_enabled
