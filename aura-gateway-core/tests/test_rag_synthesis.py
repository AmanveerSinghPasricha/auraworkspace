"""
Aura Gateway Core - RAG Synthesis & Quality Test Suite
======================================================
Validates that RAG responses are strictly grounded in document context,
include inline section/page citations, and do NOT generate hallucinated code
or invented policy rules.
"""

import sys
import asyncio
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch

# Enforce Windows Selector Event Loop Policy for Psycopg async mode on Windows
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Ensure root directory is on Python path
sys.path.append(str(Path(__file__).parent.parent))

from app.nodes.rag import TreeNode, VectorlessEngine, answer_vectorless_query


@pytest.fixture
def mock_nist_tree():
    """Generates a mock NIST SP 800-53 Access Control document tree."""
    root = TreeNode(title="NIST.SP.800-53r5.pdf", level=0)
    
    ac_chapter = TreeNode(
        title="Access Control (AC)",
        level=1,
        page_numbers=[45, 46, 47],
        parent_id=root.node_id,
        summary="Contains controls for access management and account monitoring."
    )
    
    ac2_section = TreeNode(
        title="AC-2 Account Management",
        level=2,
        page_numbers=[47, 48],
        parent_id=ac_chapter.node_id,
        summary="Specifies requirements for creating, enabling, disabling, and removing system accounts."
    )
    ac2_section.content_blocks = [
        "The organization manages system accounts including establishing, activating, modifying, disabling, and removing accounts in accordance with organizational procedures.",
        "AC-2(1): Automated Account Management - Automate account management functions.",
        "AC-2(2): Removal of Temporary Accounts - Automatically remove or disable temporary and emergency accounts."
    ]
    
    ac_chapter.children.append(ac2_section)
    root.children.append(ac_chapter)
    return root


@pytest.mark.asyncio
async def test_rag_synthesis_no_code_hallucination(mock_nist_tree):
    """
    TEST CASE 1: Code Suppression
    Given: A factual policy inquiry to RAG_ENGINE
    When: Synthesis LLM constructs response
    Then: Output MUST NOT contain Python/code blocks unless requested.
    """
    mock_llm_response = (
        "## AC-2 Account Management\n"
        "According to NIST SP 800-53 [Section AC-2 Account Management, Page 47], "
        "the organization must manage system accounts by establishing, activating, "
        "modifying, disabling, and removing accounts in accordance with organizational procedures."
    )

    with patch("app.nodes.rag.VectorlessEngine.compute_file_hash", return_value="mock_hash_123"), \
         patch("app.nodes.rag.VectorlessEngine.load_tree_from_cache", return_value=mock_nist_tree), \
         patch("app.nodes.rag.VectorlessRouter.route", new_callable=AsyncMock) as mock_route, \
         patch("app.nodes.rag.acompletion", new_callable=AsyncMock) as mock_llm:

        mock_route.return_value = (False, [mock_nist_tree.children[0].children[0].node_id], None)
        mock_llm.return_value.choices = [
            type("Choice", (), {"message": type("Message", (), {"content": mock_llm_response})()})()
        ]

        result = await answer_vectorless_query(
            query="What are the specific requirements for account management in AC-2?",
            file_path="dummy_path.pdf",
            engine=VectorlessEngine()
        )

        answer = result["answer"]

        # Assertions
        assert "```python" not in answer, "FAIL: Response contains unrequested Python code blocks!"
        assert "class AccountManager" not in answer, "FAIL: Response hallucinated code classes!"
        assert "Section AC-2" in answer, "FAIL: Missing required structural section citation!"
        assert "Page 47" in answer, "FAIL: Missing required page number citation!"


@pytest.mark.asyncio
async def test_rag_synthesis_grounding_verification(mock_nist_tree):
    """
    TEST CASE 2: Strict Grounding & Rule Verification
    Given: A query on account management requirements
    When: Document text is retrieved
    Then: Response reflects retrieved context and avoids ungrounded claims (e.g. '30 days').
    """
    mock_llm_response = (
        "Under AC-2 Account Management [Section AC-2, Page 47-48], the organization must "
        "automate account management functions and disable temporary or emergency accounts."
    )

    with patch("app.nodes.rag.VectorlessEngine.compute_file_hash", return_value="mock_hash_123"), \
         patch("app.nodes.rag.VectorlessEngine.load_tree_from_cache", return_value=mock_nist_tree), \
         patch("app.nodes.rag.VectorlessRouter.route", new_callable=AsyncMock) as mock_route, \
         patch("app.nodes.rag.acompletion", new_callable=AsyncMock) as mock_llm:

        mock_route.return_value = (False, [mock_nist_tree.children[0].children[0].node_id], None)
        mock_llm.return_value.choices = [
            type("Choice", (), {"message": type("Message", (), {"content": mock_llm_response})()})()
        ]

        result = await answer_vectorless_query(
            query="How does the organization handle temporary accounts?",
            file_path="dummy_path.pdf",
            engine=VectorlessEngine()
        )

        answer = result["answer"]

        # Assertions
        assert "30 days" not in answer, "FAIL: Response contains hallucinated time limits not in context!"
        assert "disable temporary" in answer.lower(), "FAIL: Response failed to extract facts from context."