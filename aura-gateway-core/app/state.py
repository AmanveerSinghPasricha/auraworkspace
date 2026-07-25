"""
Aura Gateway Core - Central GraphState Schema & Models
"""

from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from langchain_core.messages import BaseMessage


class UserProfileContext(BaseModel):
    """Contextual metadata regarding the active user."""
    user_id: str = Field(default="user_default")
    department: Optional[str] = Field(default="Engineering")
    role_title: Optional[str] = Field(default="Machine Learning Engineer")
    preferred_language: Optional[str] = Field(default="English")


class RouterState(BaseModel):
    """Metadata set by supervisor_router_node."""
    active_route: str = Field(default="GENERAL_AGENT")
    confidence: float = Field(default=1.0)
    reasoning: str = Field(default="")


class FinOpsLedger(BaseModel):
    """Accounting model for tracking token usage and cost metrics."""
    total_prompt_tokens: int = Field(default=0)
    total_completion_tokens: int = Field(default=0)
    total_cost_usd: float = Field(default=0.0)

    def log_transaction_usage(self, model_response_metadata: dict, model_pricing_rates: dict = None):
        self.total_prompt_tokens += model_response_metadata.get("prompt_tokens", 0)
        self.total_completion_tokens += model_response_metadata.get("completion_tokens", 0)


class GraphState(BaseModel):
    """
    Central state schema flowing through every node in the LangGraph execution graph.
    """
    messages: List[BaseMessage] = Field(default_factory=list)
    user_context: Optional[UserProfileContext] = Field(default_factory=UserProfileContext)
    router_state: Optional[RouterState] = Field(default=None)
    staged_action_payload: Optional[Dict[str, Any]] = Field(default_factory=dict)
    extracted_data_matrix: Optional[Dict[str, Any]] = Field(default_factory=dict)
    finops_ledger: FinOpsLedger = Field(default_factory=FinOpsLedger)
    validation_errors: List[str] = Field(default_factory=list)
