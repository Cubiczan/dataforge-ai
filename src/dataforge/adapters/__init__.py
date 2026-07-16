"""CritMin Oracle model adapter.

CritMin is a critical-mineral risk-scoring model:
  - Input:  SEC 10-K filings + supply-chain news (NLP features)
  - Output: 0-100 risk score per mineral/commodity

This adapter exposes the features the agent should monitor for distribution
shift (sentiment polarity, mention count, price-deviation signal) and maps
DataHub MLFeature URNs to local feature extractors so the detector can pull
fresh values during each poll cycle.
"""
from __future__ import annotations

import logging
import random
import re
from dataclasses import dataclass
from typing import Callable

import numpy as np

log = logging.getLogger(__name__)


@dataclass
class CritMinFeature:
    """A feature consumed by the CritMin risk-scoring model."""

    feature_id: str
    description: str
    extractor: Callable[[str], float]


# -----------------------------------------------------------------------------
# Feature extractors (deterministic stubs for the demo; swap for the real NLP
# pipeline from the original CritMin Oracle project).
# -----------------------------------------------------------------------------

def _sentiment_polarity(text: str) -> float:
    """Crude sentiment proxy: (pos_words - neg_words) / (pos_words + neg_words)."""
    pos = len(re.findall(r"\b(growth|strong|robust|expansion|improved|gain)\b", text, re.I))
    neg = len(re.findall(r"\b(decline|weak|loss|risk|shortage|disruption|lawsuit)\b", text, re.I))
    if pos + neg == 0:
        return 0.0
    return (pos - neg) / (pos + neg)


def _mention_count(text: str) -> float:
    """Number of mineral/commodity mentions in the text."""
    minerals = ["lithium", "cobalt", "nickel", "copper", "rare earth", "graphite", "manganese"]
    return float(sum(len(re.findall(rf"\b{m}\b", text, re.I)) for m in minerals))


def _price_deviation_signal(text: str) -> float:
    """Proxy for price-deviation mention intensity."""
    return float(len(re.findall(r"\b(price|surge|spike|drop|volatility)\b", text, re.I)))


# -----------------------------------------------------------------------------
# Registry of features the agent should monitor
# -----------------------------------------------------------------------------

CRITMIN_FEATURES: list[CritMinFeature] = [
    CritMinFeature(
        feature_id="critmin.sentiment_polarity",
        description="Mean sentiment polarity across SEC filings + news in window.",
        extractor=_sentiment_polarity,
    ),
    CritMinFeature(
        feature_id="critmin.mineral_mention_count",
        description="Total critical-mineral mentions across the document corpus.",
        extractor=_mention_count,
    ),
    CritMinFeature(
        feature_id="critmin.price_deviation_signal",
        description="Proxy for price-deviation signal extracted from filings.",
        extractor=_price_deviation_signal,
    ),
]


def sample_feature_values(feature: CritMinFeature, corpus: list[str]) -> list[float]:
    """Run a feature extractor over a corpus and return the resulting samples."""
    return [feature.extractor(doc) for doc in corpus]


def make_synthetic_corpus(n_docs: int = 100, drift: bool = False) -> list[str]:
    """Generate a synthetic SEC-filing-like corpus for demo purposes.

    With drift=True, injects language that systematically shifts the sentiment
    and mention-count distributions so the detector has something to find.
    """
    base_sentences = [
        "The company reported robust growth in lithium supply contracts.",
        "Cobalt prices remained stable throughout the quarter.",
        "Nickel demand showed steady expansion across EV markets.",
        "Copper mining operations continued without disruption.",
        "Rare earth supply chains improved year over year.",
    ]
    drift_sentences = [
        "Cobalt supply disruption risk increased sharply this quarter.",
        "A major lithium shortage was reported across multiple suppliers.",
        "Nickel price volatility spiked following regulatory changes.",
        "Copper mining faced unexpected decline and lawsuit filings.",
        "Rare earth export restrictions caused significant loss of inventory.",
    ]

    rng = random.Random(42 if not drift else 1337)
    pool = drift_sentences if drift else base_sentences
    return [rng.choice(pool) for _ in range(n_docs)]


def risk_score(sentiment: float, mentions: float, price_signal: float) -> float:
    """The CritMin 0-100 risk score (compact form of the real model)."""
    raw = (
        -25.0 * np.clip(sentiment, -1, 1)               # negative sentiment raises risk
        + 0.8 * mentions                                # more mentions = more attention
        + 5.0 * price_signal                            # price-deviation mentions raise risk
        + 30.0                                          # baseline
    )
    return float(np.clip(raw, 0.0, 100.0))
