from __future__ import annotations

from agent.node.node_logging import log_node_runtime
from agent.node.verification_utils import get_review_materials
from agent.state import OverallState


@log_node_runtime("verification_prepare_node")
def verification_prepare_node(state: OverallState) -> OverallState:
    return {"verification_materials": get_review_materials(state)}
