"""stream_stages — centralized streaming stage definitions with user-friendly labels.

Single source of truth for all SSE stage events emitted by the query pipeline.
Stage IDs are stable (used for routing/filtering); labels are user-friendly verbs
chosen randomly via weighted selection on each emission.

The verb pool uses three weighted tiers:
  - Cognitive  (40%): thinking / reasoning verbs
  - Analytical (35%): processing / data verbs
  - Constructive (25%): building / assembling verbs
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import TypedDict

_COGNITIVE_WEIGHT = 4
_ANALYTICAL_WEIGHT = 35  # percentage points for analytical tier
_CONSTRUCTIVE_WEIGHT = 25  # percentage points for constructive tier

_COGNITIVE = [
    "Pondering",
    "Musing",
    "Cogitating",
    "Ruminating",
    "Speculating",
    "Considering",
    "Imagining",
    "Daydreaming",
]

_ANALYTICAL = [
    "Calculating",
    "Analyzing",
    "Investigating",
    "Scrutinizing",
    "Deconstructing",
    "Parsing",
    "Traversing",
    "Correlating",
    "Scanning",
    "Cataloging",
]

_CONSTRUCTIVE = [
    "Scheming",
    "Brewing",
    "Fabricating",
    "Assembling",
    "Synthesizing",
    "Orchestrating",
    "Constructing",
    "Calibrating",
    "Optimizing",
    "Transmuting",
]

_SPINNERS = _COGNITIVE + _ANALYTICAL + _CONSTRUCTIVE

_WEIGHT_BUCKETS: list[str] = (
    [_COGNITIVE[0]] * _COGNITIVE_WEIGHT
    + _ANALYTICAL * (_ANALYTICAL_WEIGHT // 10)
    + _CONSTRUCTIVE * (_CONSTRUCTIVE_WEIGHT // 10)
)
if len(_WEIGHT_BUCKETS) < len(_SPINNERS):
    _WEIGHT_BUCKETS.extend(_SPINNERS[: len(_SPINNERS) - len(_WEIGHT_BUCKETS)])
elif len(_WEIGHT_BUCKETS) > len(_SPINNERS):
    _WEIGHT_BUCKETS = _WEIGHT_BUCKETS[: len(_SPINNERS)]


def _random_label() -> str:
    return random.choice(_WEIGHT_BUCKETS)


class StageEvent(TypedDict):
    type: str
    stage: str
    label: str
    progress: int


@dataclass(frozen=True, slots=True)
class _StageDef:
    stage_id: str
    progress: int


UNDERSTANDING = _StageDef(stage_id="understanding", progress=15)
BUILDING_CONTEXT = _StageDef(stage_id="building_context", progress=30)
GENERATING_SQL = _StageDef(stage_id="generating_sql", progress=55)
RUNNING_QUERY = _StageDef(stage_id="running_query", progress=75)
INTERPRETING = _StageDef(stage_id="interpreting", progress=88)
ANSWERING = _StageDef(stage_id="answering", progress=92)


def emit(stage_def: _StageDef) -> StageEvent:
    return {
        "type": "stage",
        "stage": stage_def.stage_id,
        "label": _random_label() + "...",
        "progress": stage_def.progress,
    }
