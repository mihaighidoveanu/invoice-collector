"""Integration tests: verify connection to LLM and Gmail API.

These tests hit real services and require valid credentials.
Run with: pytest tests/integration/ -v

Skip integration tests: pytest tests/unit/ -v
"""

from agent.gmail_tools import _build_service as _build_gmail_service
from agent.statement_parser import _build_llm

# ---------------------------------------------------------------------------
# LLM Integration Test
# ---------------------------------------------------------------------------


def test_llm_connection() -> None:
    """Verify AWS Bedrock LLM is reachable and responds to a minimal prompt."""
    llm = _build_llm()

    # Minimal test: ask it to echo a word back.
    response = llm.invoke("Say 'OK' and nothing else.")

    # Verify we got a response
    assert response is not None
    assert response.content is not None
    content = str(response.content).strip().upper()

    # Should contain 'OK' somewhere in the response
    assert "OK" in content, f"Expected 'OK' in response, got: {response.content}"


# ---------------------------------------------------------------------------
# Gmail Integration Test
# ---------------------------------------------------------------------------


def test_gmail_connection() -> None:
    """Verify Gmail API is reachable and credentials are valid.

    This calls users().getProfile() which is cheap and only requires
    basic gmail.readonly permission.
    """
    service = _build_gmail_service()

    # Minimal test: fetch user profile
    profile = service.users().getProfile(userId="me").execute()

    # Verify we got valid profile data
    assert profile is not None
    assert "emailAddress" in profile
    assert "@" in profile["emailAddress"]
    assert profile["messagesTotal"] >= 0
