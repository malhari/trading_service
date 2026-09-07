"""LLM integration for trade validation and analysis."""

import json
import logging
import os
from typing import Any, Dict, Optional

from core.config import get_config

logger = logging.getLogger(__name__)


class LLMRouter:
    """Routes LLM requests and parses responses."""
    
    def __init__(self):
        self.config = get_config()
        self._client = None
    
    def _get_client(self):
        """Lazy load the LLM client."""
        if self._client is None and self.config.llm.enabled:
            try:
                if self.config.llm.provider == "openai":
                    from langchain_openai import ChatOpenAI
                    
                    api_key = os.getenv("OPENAI_API_KEY")
                    if not api_key:
                        logger.warning("OPENAI_API_KEY not set, LLM features disabled")
                        return None
                    
                    self._client = ChatOpenAI(
                        model=self.config.llm.model,
                        temperature=0,
                        api_key=api_key
                    )
                    logger.info(f"LLM client initialized: {self.config.llm.model}")
                    
            except ImportError as e:
                logger.warning(f"LLM dependencies not installed: {e}")
            except Exception as e:
                logger.error(f"Failed to initialize LLM: {e}")
        
        return self._client
    
    def run(self, prompt: str) -> Dict[str, Any]:
        """
        Run LLM with a prompt and return parsed response.
        
        Args:
            prompt: The prompt to send to LLM.
        
        Returns:
            Parsed JSON response or default dict.
        """
        if not self.config.llm.enabled:
            return {"allow_trade": True, "reason": "LLM disabled"}
        
        client = self._get_client()
        if client is None:
            return {"allow_trade": True, "reason": "LLM not available"}
        
        try:
            response = client.invoke(prompt)
            content = response.content
            
            # Try to parse JSON from response
            result = self._parse_json_response(content)
            
            logger.debug(f"LLM response: {result}")
            return result
            
        except Exception as e:
            logger.error(f"LLM request failed: {e}")
            return {"allow_trade": True, "reason": f"LLM error: {e}"}
    
    def _parse_json_response(self, content: str) -> Dict[str, Any]:
        """Parse JSON from LLM response."""
        # Try direct JSON parse
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            pass
        
        # Try to extract JSON from markdown code block
        if "```json" in content:
            start = content.find("```json") + 7
            end = content.find("```", start)
            if end > start:
                try:
                    return json.loads(content[start:end].strip())
                except json.JSONDecodeError:
                    pass
        
        # Try to find JSON object in text
        start = content.find("{")
        end = content.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                return json.loads(content[start:end])
            except json.JSONDecodeError:
                pass
        
        # Default response
        logger.warning(f"Could not parse LLM response: {content[:200]}")
        return {"allow_trade": True, "reason": "Could not parse LLM response"}
    
    def analyze_market_sentiment(self, symbol: str) -> Dict[str, Any]:
        """
        Analyze market sentiment for a symbol.
        
        Args:
            symbol: Trading symbol.
        
        Returns:
            Sentiment analysis result.
        """
        prompt = f"""
        Analyze the current market sentiment for {symbol} (Indian stock).
        
        Consider:
        1. Recent market trends
        2. Sector performance
        3. Overall market conditions
        
        Respond with JSON:
        {{
            "sentiment": "bullish" | "bearish" | "neutral",
            "confidence": 0.0 to 1.0,
            "factors": ["factor1", "factor2"],
            "recommendation": "favor_long" | "favor_short" | "no_preference"
        }}
        """
        
        return self.run(prompt)
    
    def validate_trade_setup(
        self,
        symbol: str,
        signal_type: str,
        entry: float,
        sl: float,
        target: float,
        volume_ratio: float
    ) -> Dict[str, Any]:
        """
        Validate a trade setup with LLM.
        
        Args:
            symbol: Trading symbol.
            signal_type: Type of signal.
            entry: Entry price.
            sl: Stop loss price.
            target: Target price.
            volume_ratio: Volume relative to average.
        
        Returns:
            Validation result.
        """
        risk = abs(entry - sl)
        reward = abs(target - entry)
        rr_ratio = reward / risk if risk > 0 else 0
        
        prompt = f"""
        Validate this breakout trade setup:
        
        Symbol: {symbol}
        Signal: {signal_type}
        Entry: ₹{entry:.2f}
        Stop Loss: ₹{sl:.2f}
        Target: ₹{target:.2f}
        Risk: ₹{risk:.2f}
        Reward: ₹{reward:.2f}
        Risk-Reward Ratio: {rr_ratio:.2f}
        Volume Ratio: {volume_ratio:.2f}x average
        
        Evaluate:
        1. Is the risk-reward acceptable for intraday?
        2. Is volume confirmation adequate?
        3. Any red flags in this setup?
        
        Respond with JSON:
        {{
            "allow_trade": true | false,
            "confidence": 0.0 to 1.0,
            "reason": "explanation",
            "suggestions": ["suggestion1", "suggestion2"]
        }}
        """
        
        return self.run(prompt)


# Singleton instance
_llm_router: Optional[LLMRouter] = None


def get_llm_router() -> LLMRouter:
    """Get singleton LLM router."""
    global _llm_router
    if _llm_router is None:
        _llm_router = LLMRouter()
    return _llm_router
