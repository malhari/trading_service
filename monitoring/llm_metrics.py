"""Monitoring, logging, and metrics for the trading service."""

import logging
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
import sys


def setup_logging(
    log_level: str = "INFO",
    log_file: Optional[str] = None,
    json_format: bool = False
) -> logging.Logger:
    """
    Setup logging configuration.
    
    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR).
        log_file: Optional file path for logging.
        json_format: Use JSON format for logs.
    
    Returns:
        Root logger.
    """
    level = getattr(logging, log_level.upper(), logging.INFO)
    
    # Create formatters
    if json_format:
        formatter = JsonFormatter()
    else:
        formatter = logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    
    # Root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.addHandler(console_handler)
    
    # File handler
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
    
    # Reduce noise from libraries
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    
    return root_logger


class JsonFormatter(logging.Formatter):
    """JSON log formatter."""
    
    def format(self, record: logging.LogRecord) -> str:
        log_dict = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        
        if record.exc_info:
            log_dict["exception"] = self.formatException(record.exc_info)
        
        return json.dumps(log_dict)


class TradingMetrics:
    """Collects and reports trading metrics."""
    
    def __init__(self):
        self.start_time = datetime.now()
        self._metrics: Dict[str, Any] = {
            "signals_generated": 0,
            "trades_executed": 0,
            "trades_won": 0,
            "trades_lost": 0,
            "total_pnl": 0.0,
            "max_drawdown": 0.0,
            "risk_checks_passed": 0,
            "risk_checks_failed": 0,
            "llm_calls": 0,
            "llm_rejections": 0,
            "errors": 0,
        }
        self._trade_log: List[Dict] = []
    
    def record_signal(self):
        """Record a signal generation."""
        self._metrics["signals_generated"] += 1
    
    def record_trade(self, symbol: str, side: str, pnl: float, exit_reason: str):
        """Record a completed trade."""
        self._metrics["trades_executed"] += 1
        self._metrics["total_pnl"] += pnl
        
        if pnl > 0:
            self._metrics["trades_won"] += 1
        else:
            self._metrics["trades_lost"] += 1
        
        self._trade_log.append({
            "timestamp": datetime.now().isoformat(),
            "symbol": symbol,
            "side": side,
            "pnl": pnl,
            "exit_reason": exit_reason
        })
    
    def record_risk_check(self, passed: bool):
        """Record a risk check result."""
        if passed:
            self._metrics["risk_checks_passed"] += 1
        else:
            self._metrics["risk_checks_failed"] += 1
    
    def record_llm_call(self, rejected: bool = False):
        """Record an LLM call."""
        self._metrics["llm_calls"] += 1
        if rejected:
            self._metrics["llm_rejections"] += 1
    
    def record_error(self):
        """Record an error."""
        self._metrics["errors"] += 1
    
    def update_drawdown(self, drawdown: float):
        """Update max drawdown."""
        if drawdown > self._metrics["max_drawdown"]:
            self._metrics["max_drawdown"] = drawdown
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get all metrics."""
        uptime = datetime.now() - self.start_time
        
        metrics = self._metrics.copy()
        metrics["uptime_seconds"] = uptime.total_seconds()
        metrics["win_rate"] = (
            self._metrics["trades_won"] / self._metrics["trades_executed"] * 100
            if self._metrics["trades_executed"] > 0 else 0
        )
        
        return metrics
    
    def get_summary(self) -> str:
        """Get human-readable summary."""
        m = self.get_metrics()
        
        return f"""
=== Trading Session Summary ===
Uptime: {m['uptime_seconds']/60:.1f} minutes
Signals Generated: {m['signals_generated']}
Trades Executed: {m['trades_executed']}
  - Won: {m['trades_won']}
  - Lost: {m['trades_lost']}
  - Win Rate: {m['win_rate']:.1f}%
Total P&L: ₹{m['total_pnl']:.2f}
Max Drawdown: ₹{m['max_drawdown']:.2f}
Risk Checks: {m['risk_checks_passed']} passed, {m['risk_checks_failed']} failed
LLM Calls: {m['llm_calls']} ({m['llm_rejections']} rejections)
Errors: {m['errors']}
================================
"""
    
    def export_trades(self, filepath: str):
        """Export trade log to JSON file."""
        with open(filepath, 'w') as f:
            json.dump(self._trade_log, f, indent=2)


def health_check() -> Dict[str, Any]:
    """
    Perform system health check.
    
    Returns:
        Health status dict.
    """
    from core.config import get_config
    from core.session_manager import get_session_manager
    from data.kite_client import get_kite_client
    
    config = get_config()
    session = get_session_manager()
    
    health = {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "checks": {}
    }
    
    # Config check
    health["checks"]["config"] = {
        "status": "ok",
        "mode": config.mode.value,
        "capital": config.capital
    }
    
    # Session check
    session_info = session.get_session_info()
    health["checks"]["session"] = {
        "status": "ok",
        **session_info
    }
    
    # Kite connection check
    if config.mode.value == "LIVE":
        kite = get_kite_client()
        health["checks"]["kite"] = {
            "status": "ok" if kite.is_connected else "disconnected",
            "authenticated": kite._access_token is not None
        }
    else:
        health["checks"]["kite"] = {
            "status": "skipped",
            "reason": "Paper trading mode"
        }
    
    # Set overall status
    failed_checks = [
        k for k, v in health["checks"].items() 
        if v.get("status") not in ["ok", "skipped"]
    ]
    
    if failed_checks:
        health["status"] = "degraded"
        health["failed_checks"] = failed_checks
    
    return health


# Singleton metrics instance
_metrics: Optional[TradingMetrics] = None


def get_metrics() -> TradingMetrics:
    """Get singleton metrics instance."""
    global _metrics
    if _metrics is None:
        _metrics = TradingMetrics()
    return _metrics
