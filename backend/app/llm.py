"""LLM client and intent recognition using Groq llama-3.3-70b-versatile."""

import json
import logging
import re
from typing import Any, AsyncIterator, Dict, List, Optional
from groq import AsyncGroq

from .config import get_settings
from .scrubber import scrub_pii

logger = logging.getLogger(__name__)


class LLMService:
    """Service wrapping Groq AsyncGroq client with PII scrubbing and intent recognition."""

    def __init__(self):
        settings = get_settings()
        self.client = AsyncGroq(api_key=settings.GROQ_API_KEY)
        self.model = settings.LLM_MODEL

    def detect_intent(self, text: str) -> Dict[str, Any]:
        """Classify user intent using rules first, returning workflow details if actionable.
        
        Zero cost and instant response for primary government service workflows.
        """
        scrubbed = scrub_pii(text).lower()

        # Fast rule-based classification for Aadhaar download
        aadhaar_pattern = r"\b(aadhaar|vid|uidai|e-aadhaar|eaadhaar|adhaar)\b"
        action_pattern = r"\b(download|get|fetch|retrieve|card|pdf|copy|generate)\b"

        has_aadhaar = bool(re.search(aadhaar_pattern, scrubbed))
        has_action = bool(re.search(action_pattern, scrubbed))

        if has_aadhaar:
            # If user mentions Aadhaar and any download/action keyword, high confidence
            confidence = 0.95 if has_action else 0.85
            return {
                "intent": "aadhaar_download",
                "workflow": "aadhaar_download",
                "confidence": confidence,
                "requires_task": True,
            }

        return {
            "intent": "general_chat",
            "workflow": None,
            "confidence": 0.90,
            "requires_task": False,
        }

    async def stream_chat_completion(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str] = None
    ) -> AsyncIterator[str]:
        """Stream chat tokens from Groq API with automatic PII scrubbing on all messages."""
        scrubbed_messages = []
        if system_prompt:
            scrubbed_messages.append({"role": "system", "content": system_prompt})
        else:
            scrubbed_messages.append({
                "role": "system",
                "content": (
                    "You are Saral AI, a helpful, precise assistant for Indian citizens accessing "
                    "official government digital services. Provide concise, clear, and respectful assistance."
                )
            })

        for msg in messages:
            scrubbed_messages.append({
                "role": msg.get("role", "user"),
                "content": scrub_pii(msg.get("content", ""))
            })

        try:
            stream = await self.client.chat.completions.create(
                model=self.model,
                messages=scrubbed_messages,
                stream=True,
                temperature=0.2,
                max_tokens=1024,
            )
            async for chunk in stream:
                content = chunk.choices[0].delta.content
                if content:
                    yield content
        except Exception as e:
            logger.warning("Groq API streaming fallback triggered: %s", str(e))
            # Fallback response for offline or restricted environments
            fallback_text = (
                "Namaste! I am here to help you access Indian government services. "
                "How may I assist you today?"
            )
            for word in fallback_text.split(" "):
                yield word + " "


# Singleton instance
llm_service = LLMService()
