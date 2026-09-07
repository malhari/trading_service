"""LLM integration for trade validation and analysis."""

import json
import logging
import os
import requests
from typing import Any, Dict, Optional

from core.config import get_config

logger = logging.getLogger(__name__)


class LLMRouter:
    """Routes LLM requests and parses responses.
    
    Supports multiple providers:
    - openai: OpenAI API (GPT models)
    - ollama: Local Ollama server (Llama, Mistral, etc.)
    - llamacpp: Local llama.cpp server
    - lmstudio: LM Studio local server
    """
    
    def __init__(self):
        self.config = get_config()
        self._client = None
        self._provider = self.config.llm.provider.lower()
    
    def _get_client(self):
        """Lazy load the LLM client."""
        if self._client is None and self.config.llm.enabled:
            try:
                if self._provider == "openai":
                    self._client = self._init_openai()
                elif self._provider in ["ollama", "llamacpp", "lmstudio"]:
                    self._client = self._init_local_llm()
                else:
                    logger.warning(f"Unknown LLM provider: {self._provider}")
                    
            except ImportError as e:
                logger.warning(f"LLM dependencies not installed: {e}")
            except Exception as e:
                logger.error(f"Failed to initialize LLM: {e}")
        
        return self._client
    
    def _init_openai(self):
        """Initialize OpenAI client."""
        from langchain_openai import ChatOpenAI
        
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            logger.warning("OPENAI_API_KEY not set, LLM features disabled")
            return None
        
        client = ChatOpenAI(
            model=self.config.llm.model,
            temperature=0,
            api_key=api_key
        )
        logger.info(f"OpenAI client initialized: {self.config.llm.model}")
        return client
    
    def _init_local_llm(self):
        """Initialize local LLM client (Ollama, llama.cpp, LM Studio)."""
        # Get base URL from config or environment
        base_url = os.getenv("LLAMA_BASE_URL", self.config.llm.base_url or "http://localhost:11434")
        model = os.getenv("LLAMA_MODEL", self.config.llm.model or "llama3.2")
        
        if self._provider == "ollama":
            # Ollama uses /api/generate or /api/chat
            try:
                from langchain_ollama import ChatOllama
                client = ChatOllama(
                    model=model,
                    base_url=base_url,
                    temperature=0
                )
                logger.info(f"Ollama client initialized: {model} @ {base_url}")
                return client
            except ImportError:
                # Fallback to direct API
                logger.info(f"Using direct Ollama API: {model} @ {base_url}")
                return {"type": "ollama_direct", "base_url": base_url, "model": model}
        
        elif self._provider == "llamacpp":
            # llama.cpp server uses OpenAI-compatible API
            base_url = os.getenv("LLAMA_BASE_URL", "http://localhost:8080")
            try:
                from langchain_openai import ChatOpenAI
                client = ChatOpenAI(
                    model=model,
                    base_url=f"{base_url}/v1",
                    api_key="not-needed",
                    temperature=0
                )
                logger.info(f"llama.cpp client initialized: {model} @ {base_url}")
                return client
            except ImportError:
                return {"type": "llamacpp_direct", "base_url": base_url, "model": model}
        
        elif self._provider == "lmstudio":
            # LM Studio uses OpenAI-compatible API
            base_url = os.getenv("LLAMA_BASE_URL", "http://localhost:1234")
            try:
                from langchain_openai import ChatOpenAI
                client = ChatOpenAI(
                    model=model,
                    base_url=f"{base_url}/v1",
                    api_key="not-needed",
                    temperature=0
                )
                logger.info(f"LM Studio client initialized: {model} @ {base_url}")
                return client
            except ImportError:
                return {"type": "lmstudio_direct", "base_url": base_url, "model": model}
        
        return None
    
    def _call_ollama_direct(self, prompt: str, client_config: dict) -> str:
        """Direct API call to Ollama."""
        url = f"{client_config['base_url']}/api/generate"
        
        payload = {
            "model": client_config['model'],
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0,
                "num_predict": 500  # Limit response length for faster generation
            }
        }
        
        try:
            # Increased timeout to 180 seconds for larger models
            response = requests.post(url, json=payload, timeout=180)
            response.raise_for_status()
            return response.json().get("response", "")
        except requests.exceptions.Timeout:
            logger.error("Ollama request timed out. Model may still be loading or is too slow.")
            raise Exception("LLM timeout - try again or use a smaller model")
        except requests.exceptions.ConnectionError:
            logger.error("Cannot connect to Ollama. Is it running?")
            raise Exception("Cannot connect to Ollama at localhost:11434. Run 'ollama serve' first.")
        except Exception as e:
            logger.error(f"Ollama API error: {e}")
            raise
    
    def _call_openai_compatible_direct(self, prompt: str, client_config: dict) -> str:
        """Direct API call to OpenAI-compatible server (llama.cpp, LM Studio)."""
        url = f"{client_config['base_url']}/v1/chat/completions"
        
        payload = {
            "model": client_config['model'],
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
            "max_tokens": 500  # Limit response length
        }
        
        try:
            # Increased timeout to 180 seconds for larger models
            response = requests.post(url, json=payload, timeout=180)
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"]
        except requests.exceptions.Timeout:
            logger.error("LLM request timed out")
            raise Exception("LLM timeout - try again or use a smaller model")
        except Exception as e:
            logger.error(f"LLM API error: {e}")
            raise
    
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
            # Handle direct API clients (dict config)
            if isinstance(client, dict):
                if client["type"] == "ollama_direct":
                    content = self._call_ollama_direct(prompt, client)
                else:
                    content = self._call_openai_compatible_direct(prompt, client)
            else:
                # LangChain client
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
        volume_ratio: float,
        return_prompt: bool = False
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
            return_prompt: If True, include the prompt in the response.
        
        Returns:
            Validation result.
        """
        risk = abs(entry - sl)
        reward = abs(target - entry)
        rr_ratio = reward / risk if risk > 0 else 0
        
        prompt = f"""Validate this breakout trade setup:

Symbol: {symbol}
Signal: {signal_type}
Entry: Rs.{entry:.2f}
Stop Loss: Rs.{sl:.2f}
Target: Rs.{target:.2f}
Risk: Rs.{risk:.2f}
Reward: Rs.{reward:.2f}
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
}}"""
        
        result = self.run(prompt)
        
        if return_prompt:
            result['_prompt'] = prompt
        
        return result


# Singleton instance
_llm_router: Optional[LLMRouter] = None


def get_llm_router() -> LLMRouter:
    """Get singleton LLM router."""
    global _llm_router
    if _llm_router is None:
        _llm_router = LLMRouter()
    return _llm_router
