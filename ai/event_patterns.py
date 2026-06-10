"""Historical event-pattern knowledge base and matcher."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from loguru import logger

from models import PatternMatch

try:
    from rapidfuzz import fuzz
except ImportError:  # pragma: no cover - optional dependency.
    fuzz = None  # type: ignore[assignment]


EVENT_PATTERNS: dict[str, dict[str, Any]] = {
    "sec_crackdown": {
        "keywords": ["SEC", "securities", "lawsuit", "charges", "fraud", "illegal", "unregistered", "penalty", "fine", "enforcement"],
        "typical_impact": "bearish",
        "severity": "high",
        "avg_drop_percent": 15,
        "duration_days": "3-14",
        "historical_examples": [
            "SEC vs Ripple 2020 - XRP dropped 65% in 48 hours",
            "SEC charges Coinbase 2023 - BTC dropped 8%, entire market fell",
            "SEC rejects Bitcoin ETF 2019 - BTC dropped 10%",
        ],
        "confidence": 0.85,
    },
    "regulation_ban": {
        "keywords": ["ban", "banned", "prohibit", "illegal", "crackdown", "government blocks", "restrict", "CBN", "central bank blocks"],
        "typical_impact": "bearish",
        "severity": "high",
        "avg_drop_percent": 20,
        "duration_days": "5-21",
        "historical_examples": [
            "China crypto ban 2021 - BTC dropped 30% over 2 weeks",
            "CBN Nigeria ban 2021 - local crypto volumes dropped 70%",
            "India proposed ban 2021 - BTC dropped 15%",
        ],
        "confidence": 0.80,
    },
    "regulation_positive": {
        "keywords": ["approved", "legal", "regulated", "framework", "clarity", "licensed", "compliant", "SEC approves", "government supports"],
        "typical_impact": "bullish",
        "severity": "medium",
        "avg_gain_percent": 10,
        "duration_days": "1-5",
        "historical_examples": [
            "Bitcoin ETF approval Jan 2024 - BTC pumped 15% in 24 hours",
            "El Salvador Bitcoin legal tender 2021 - BTC gained 20%",
        ],
        "confidence": 0.75,
    },
    "exchange_hack": {
        "keywords": ["hack", "hacked", "breach", "stolen", "exploit", "vulnerability", "funds lost", "security incident", "compromised"],
        "typical_impact": "bearish",
        "severity": "high",
        "avg_drop_percent": 12,
        "duration_days": "3-7",
        "historical_examples": [
            "FTX collapse 2022 - BTC dropped 25%, entire market fell 30%",
            "Mt Gox hack 2014 - BTC dropped 36%",
            "Bybit hack Feb 2025 - ETH dropped 8% in 4 hours",
            "Binance hack 2019 - BTC dropped 5%",
        ],
        "confidence": 0.88,
    },
    "exchange_collapse": {
        "keywords": ["insolvent", "bankrupt", "collapse", "withdrawal halt", "frozen", "chapter 11", "liquidation", "shutdown"],
        "typical_impact": "bearish",
        "severity": "critical",
        "avg_drop_percent": 30,
        "duration_days": "14-60",
        "historical_examples": [
            "FTX bankruptcy Nov 2022 - BTC dropped from $21k to $15k in 7 days",
            "Celsius collapse 2022 - market dropped 25%",
            "3AC liquidation 2022 - triggered cascading 40% market drop",
        ],
        "confidence": 0.92,
    },
    "exchange_listing": {
        "keywords": ["listed on", "now available", "trading now", "launches on", "Coinbase listing", "Binance listing", "Bybit listing"],
        "typical_impact": "bullish",
        "severity": "medium",
        "avg_gain_percent": 15,
        "duration_days": "1-3",
        "historical_examples": [
            "Coinbase listings historically pump coins 20-40% on announcement",
            "Binance listing effect averages 15-30% gain within 24 hours",
        ],
        "confidence": 0.78,
    },
    "fed_rate_hike": {
        "keywords": ["Federal Reserve", "Fed raises", "interest rate hike", "rate increase", "hawkish Fed", "tightening", "FOMC hike"],
        "typical_impact": "bearish",
        "severity": "medium",
        "avg_drop_percent": 8,
        "duration_days": "1-5",
        "historical_examples": [
            "Fed 75bps hike June 2022 - BTC dropped 15% that week",
            "Fed rate hike cycle 2022 - crypto lost 70% over the year",
            "Surprise Fed hike 2023 - BTC dropped 6% in 24 hours",
        ],
        "confidence": 0.82,
    },
    "fed_rate_cut": {
        "keywords": ["Federal Reserve cuts", "rate cut", "dovish Fed", "easing", "pivot", "lower rates", "FOMC cut"],
        "typical_impact": "bullish",
        "severity": "medium",
        "avg_gain_percent": 8,
        "duration_days": "2-7",
        "historical_examples": [
            "Fed pivot signal Nov 2023 - BTC rallied 30% over following weeks",
            "Fed rate cut Sept 2024 - BTC gained 10% in 48 hours",
        ],
        "confidence": 0.78,
    },
    "inflation_data": {
        "keywords": ["CPI", "inflation", "consumer price index", "PPI", "inflation higher", "inflation lower", "core inflation"],
        "typical_impact": "variable",
        "severity": "medium",
        "duration_days": "1-3",
        "historical_examples": [
            "High CPI print - bearish for risk assets including crypto",
            "Low CPI print - bullish, signals Fed may pause hikes",
        ],
        "confidence": 0.70,
    },
    "bitcoin_halving": {
        "keywords": ["halving", "block reward", "mining reward cut", "halvening", "block subsidy"],
        "typical_impact": "bullish",
        "severity": "high",
        "avg_gain_percent": 150,
        "duration_days": "90-365",
        "historical_examples": [
            "2012 halving - BTC went from $12 to $1000 within a year",
            "2016 halving - BTC went from $650 to $20000 over 18 months",
            "2020 halving - BTC went from $8000 to $69000 over 18 months",
            "2024 halving - preceded major bull run",
        ],
        "confidence": 0.88,
    },
    "etf_approval": {
        "keywords": ["ETF approved", "ETF approval", "spot ETF", "Bitcoin ETF", "Ethereum ETF", "ETF launch", "asset manager ETF"],
        "typical_impact": "bullish",
        "severity": "high",
        "avg_gain_percent": 20,
        "duration_days": "3-30",
        "historical_examples": [
            "Bitcoin spot ETF approved Jan 2024 - BTC surged from $42k to $73k",
            "ProShares Bitcoin futures ETF 2021 - BTC pumped 40%",
        ],
        "confidence": 0.85,
    },
    "whale_movement": {
        "keywords": ["whale", "large transfer", "billion moved", "wallet transfer", "Satoshi wallet", "dormant wallet", "large holder sells"],
        "typical_impact": "bearish",
        "severity": "medium",
        "avg_drop_percent": 5,
        "duration_days": "0-2",
        "historical_examples": [
            "Old Satoshi-era wallets moving - FUD causes 5-10% drops",
            "Whale dumps tracked on chain often precede 5-15% corrections",
        ],
        "confidence": 0.65,
    },
    "institutional_adoption": {
        "keywords": ["buys Bitcoin", "adds crypto", "institutional", "treasury", "MicroStrategy", "BlackRock", "Fidelity", "corporate buys", "adds to balance sheet"],
        "typical_impact": "bullish",
        "severity": "medium",
        "avg_gain_percent": 8,
        "duration_days": "1-7",
        "historical_examples": [
            "MicroStrategy Bitcoin purchases - consistent 5-15% pumps",
            "Tesla adds Bitcoin to treasury 2021 - BTC gained 20%",
            "BlackRock ETF filing 2023 - BTC pumped 25% over following weeks",
        ],
        "confidence": 0.80,
    },
    "institutional_sell": {
        "keywords": ["sells Bitcoin", "dumps crypto", "reduces exposure", "exits position", "selling pressure", "distribution"],
        "typical_impact": "bearish",
        "severity": "medium",
        "avg_drop_percent": 8,
        "duration_days": "1-5",
        "historical_examples": [
            "Tesla sells Bitcoin 2021 - BTC dropped 10%",
            "MassMutual reduces crypto - mild bearish pressure",
        ],
        "confidence": 0.72,
    },
    "elon_tweet": {
        "keywords": ["Elon", "Musk", "Tesla CEO", "SpaceX CEO", "Dogecoin", "DOGE", "Elon says"],
        "typical_impact": "variable",
        "severity": "high",
        "duration_days": "0-2",
        "historical_examples": [
            "Elon tweets Doge - DOGE pumped 50% in hours multiple times",
            "Elon removes Bitcoin from Tesla 2021 - BTC dropped 15%",
            "Elon changes Twitter logo to Doge 2023 - DOGE pumped 30%",
        ],
        "confidence": 0.75,
    },
    "stablecoin_depeg": {
        "keywords": ["depeg", "de-peg", "lost peg", "not 1 dollar", "USDT concern", "USDC concern", "DAI concern", "stablecoin risk"],
        "typical_impact": "bearish",
        "severity": "critical",
        "avg_drop_percent": 25,
        "duration_days": "3-30",
        "historical_examples": [
            "UST/Luna collapse May 2022 - BTC dropped 30%, Luna to zero",
            "USDC brief depeg March 2023 - crypto fell 8% in hours",
        ],
        "confidence": 0.90,
    },
    "network_upgrade": {
        "keywords": ["upgrade", "hard fork", "soft fork", "merge", "mainnet launch", "protocol upgrade", "network improvement"],
        "typical_impact": "bullish",
        "severity": "medium",
        "avg_gain_percent": 12,
        "duration_days": "3-14",
        "historical_examples": [
            "Ethereum Merge Sept 2022 - ETH pumped 50% in weeks prior",
            "Ethereum Shanghai upgrade 2023 - ETH gained 10%",
        ],
        "confidence": 0.72,
    },
    "network_attack": {
        "keywords": ["51% attack", "network attack", "double spend", "blockchain attack", "validator attack", "consensus failure"],
        "typical_impact": "bearish",
        "severity": "critical",
        "avg_drop_percent": 30,
        "duration_days": "7-30",
        "historical_examples": [],
        "confidence": 0.88,
    },
}


@dataclass(slots=True)
class PatternMatcher:
    """Match market headlines against known historical event patterns."""

    threshold: float = 80.0

    def match_headlines(self, headlines: list[str]) -> list[dict[str, Any]]:
        """Scan all headlines for keyword matches from EVENT_PATTERNS."""

        matches: list[dict[str, Any]] = []
        for headline in headlines:
            lowered = headline.lower()
            for pattern_name, pattern in EVENT_PATTERNS.items():
                for keyword in pattern["keywords"]:
                    score = self._match_score(lowered, keyword.lower())
                    if score < self.threshold:
                        continue
                    match = PatternMatch(
                        pattern_name=pattern_name,
                        matched_keyword=keyword,
                        headline=headline,
                        match_score=score,
                        typical_impact=str(pattern["typical_impact"]),
                        severity=str(pattern["severity"]),
                        confidence=float(pattern.get("confidence", 0.0)),
                        historical_examples=list(pattern.get("historical_examples", [])),
                        avg_drop_percent=float(pattern["avg_drop_percent"]) if "avg_drop_percent" in pattern else None,
                        avg_gain_percent=float(pattern["avg_gain_percent"]) if "avg_gain_percent" in pattern else None,
                        duration_days=pattern.get("duration_days"),
                    )
                    matches.append(match.to_dict())
        if matches:
            logger.bind(pattern_log=True).info(f"Matched event patterns: {matches}")
        return matches

    def aggregate_pattern_score(self, matches: list[dict[str, Any]]) -> float:
        """Collapse pattern matches into a bearish/bullish score from -1.0 to 1.0."""

        if not matches:
            return 0.0
        total = 0.0
        weight = 0.0
        for match in matches:
            confidence = float(match.get("confidence", 0.0))
            impact = str(match.get("typical_impact", "variable"))
            severity = str(match.get("severity", "medium"))
            severity_factor = {"low": 0.5, "medium": 1.0, "high": 1.35, "critical": 1.75}.get(severity, 1.0)
            direction = 0.0
            if impact == "bullish":
                direction = 1.0
            elif impact == "bearish":
                direction = -1.0
            total += direction * confidence * severity_factor
            weight += severity_factor
        return round(total / max(weight, 1.0), 4)

    def has_critical_pattern(self, matches: list[dict[str, Any]]) -> bool:
        """Return True when any matched pattern is critical."""

        return any(str(match.get("severity", "")).lower() == "critical" for match in matches)

    def _match_score(self, headline: str, keyword: str) -> float:
        """Calculate a fuzzy match score."""

        if keyword in headline:
            return 100.0
        if fuzz is None:
            return 0.0
        return max(
            float(fuzz.partial_ratio(headline, keyword)),
            float(fuzz.token_set_ratio(headline, keyword)),
        )
