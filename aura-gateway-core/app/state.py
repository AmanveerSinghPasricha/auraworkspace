"""
Aura Gateway Core - Global Graph Application State Schema

This module defines the foundational Pydantic v2 data contract and state reducers
operating as the single source of truth across all LangGraph orchestration nodes[cite: 2, 5].
"""

import operator
import logging
from typing import List, Dict, Any, Optional, Literal, Annotated
from pydantic import BaseModel, Field
from langchain_core.messages import BaseMessage

# Configure module-level logger for debugging state transitions
logger = logging.getLogger(__name__)


def merge_extracted_matrices(
    existing_matrix: Dict[str, Any], incoming_matrix: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Custom state reducer function handling concurrent dictionary updates during Bulk Synchronous Parallelism (BSP) fan-in[cite: 5].

    Args:
        existing_matrix (Dict[str, Any]): The primary state matrix currently stored in thread state[cite: 5].
        incoming_matrix (Dict[str, Any]): The new payload matrix produced by a parallel worker node[cite: 5].

    Returns:
        Dict[str, Any]: A combined dictionary merging parallel node extractions without key overwrites[cite: 5].
    """
    print("🔄 [STATE REDUCER] Merging parallel extraction matrices...")
    
    try:
        # Create a copy of the existing matrix to preserve immutability
        merged_result_matrix: Dict[str, Any] = existing_matrix.copy()

        # Iterate over all key-value pairs from the incoming node payload
        for matrix_key, matrix_value in incoming_matrix.items():
            # If both entries are lists, concatenate them sequentially
            if (
                matrix_key in merged_result_matrix 
                and isinstance(merged_result_matrix[matrix_key], list) 
                and isinstance(matrix_value, list)
            ):
                merged_result_matrix[matrix_key] = merged_result_matrix[matrix_key] + matrix_value
            
            # If both entries are dictionaries, execute a recursive deep-merge
            elif (
                matrix_key in merged_result_matrix 
                and isinstance(merged_result_matrix[matrix_key], dict) 
                and isinstance(matrix_value, dict)
            ):
                merged_result_matrix[matrix_key] = merge_extracted_matrices(
                    merged_result_matrix[matrix_key], matrix_value
                )
            
            # Default behavior: assign or update key directly
            else:
                merged_result_matrix[matrix_key] = matrix_value

        print(f"✅ [STATE REDUCER] Successfully merged {len(incoming_matrix)} matrix keys.")
        return merged_result_matrix

    except Exception as state_reducer_error:
        print(f"❌ [STATE REDUCER ERROR] Failed to merge extraction matrices: {str(state_reducer_error)}")
        # Fail-safe: return incoming matrix if state merging fails
        return incoming_matrix if incoming_matrix else existing_matrix


class UserProfileContext(BaseModel):
    """
    User context baseline containing identity, department, and formatting preferences[cite: 3, 5].
    """
    user_id: str = Field(description="Unique tenant identifier string for multi-tenant isolation[cite: 3, 5]")
    department: str = Field(description="Organizational department or business unit name[cite: 5]")
    formatting_preference: str = Field(
        default="markdown", description="Response presentation format preference[cite: 5]"
    )


class CoordinateTarget(BaseModel):
    """
    Structural target parameters used by the Vectorless RAG coordinate engine[cite: 3, 5].
    """
    document_id: str = Field(description="Unique document asset identifier[cite: 5]")
    target_page: int = Field(description="Target page number within document asset[cite: 5]")
    structure_type: Literal["table", "grid", "paragraph"] = Field(
        description="Layout structural component classification[cite: 5]"
    )
    cell_coordinates: Dict[str, Any] = Field(
        default_factory=dict, description="Geometric row and column coordinate mappings[cite: 2, 5]"
    )


class ApplicationFinOpsLedger(BaseModel):
    """
    FinOps tracking engine computing micro-dollar model spend per superstep[cite: 5].
    """
    prompt_tokens: int = Field(default=0, description="Total input prompt tokens processed[cite: 5]")
    completion_tokens: int = Field(default=0, description="Total generated completion tokens[cite: 5]")
    cached_tokens_saved: int = Field(default=0, description="Input prompt tokens served via LLM cache[cite: 5]")
    accumulated_cost_usd: float = Field(default=0.0, description="Cumulative financial expenditure in USD[cite: 5]")

    def log_transaction_usage(
        self, 
        model_response_metadata: Dict[str, Any], 
        model_pricing_rates: Dict[str, float]
    ) -> None:
        """
        Natively updates token counters and computes execution expenditure inside the state vector[cite: 5].

        Args:
            model_response_metadata (Dict[str, Any]): Usage metadata dictionary from model API response[cite: 5].
            model_pricing_rates (Dict[str, float]): Per-token pricing table containing 'in', 'cached', and 'out' keys[cite: 5].
        """
        print("💰 [FINOPS LEDGER] Calculating micro-dollar model transaction spend...")
        
        try:
            # Extract token quantities safely using fallback default values
            extracted_prompt_tokens: int = model_response_metadata.get("prompt_tokens", 0)
            extracted_completion_tokens: int = model_response_metadata.get("completion_tokens", 0)
            extracted_cache_tokens: int = model_response_metadata.get("cache_read_tokens", 0)

            # Update cumulative token counters
            self.prompt_tokens += extracted_prompt_tokens
            self.completion_tokens += extracted_completion_tokens
            self.cached_tokens_saved += extracted_cache_tokens

            # Compute transaction cost incorporating prompt caching rates
            transaction_cost_usd: float = (
                ((extracted_prompt_tokens - extracted_cache_tokens) * model_pricing_rates.get("in", 0.0))
                + (extracted_cache_tokens * model_pricing_rates.get("cached", 0.0))
                + (extracted_completion_tokens * model_pricing_rates.get("out", 0.0))
            )
            
            self.accumulated_cost_usd += transaction_cost_usd
            print(f"📊 [FINOPS LEDGER] Transaction Cost: ${transaction_cost_usd:.6f} | Total Thread Cost: ${self.accumulated_cost_usd:.6f}")

        except Exception as finops_calculation_error:
            print(f"❌ [FINOPS ERROR] Failed to calculate transaction spend: {str(finops_calculation_error)}")


class GraphState(BaseModel):
    """
    Primary state vector holding active session state, memory, and guardrail flags across thread supersteps[cite: 2, 5].
    """
    messages: Annotated[List[BaseMessage], operator.add] = Field(
        default_factory=list, description="Append-only conversational message stream[cite: 5]"
    )
    user_context: Optional[UserProfileContext] = Field(
        default=None, description="Active user profile context schema[cite: 5]"
    )
    extraction_target: Optional[CoordinateTarget] = Field(
        default=None, description="Active coordinate extraction target[cite: 5]"
    )
    extracted_data_matrix: Annotated[Dict[str, Any], merge_extracted_matrices] = Field(
        default_factory=dict, description="Merged tabular extraction matrices from parallel workers[cite: 5]"
    )
    is_calculation_valid: bool = Field(
        default=False, description="Flag indicating mathematical calculation status[cite: 3, 5]"
    )
    validation_errors: List[str] = Field(
        default_factory=list, description="Validation failure details driving self-healing loops[cite: 3, 5]"
    )
    active_loop_count: int = Field(
        default=0, description="Recursion counter preventing infinite graph deadlocks[cite: 5]"
    )
    awaiting_manual_override: bool = Field(
        default=False, description="State-aware brake flag for Human-in-the-Loop interrupts[cite: 3, 5]"
    )
    staged_action_payload: Optional[Dict[str, Any]] = Field(
        default=None, description="Staged external API action parameters pending human review[cite: 3, 5]"
    )
    finops_ledger: ApplicationFinOpsLedger = Field(
        default_factory=ApplicationFinOpsLedger, description="Real-time financial usage tracker instance[cite: 5]"
    )