from laya import Router

router = Router(preload=True)

QUESTIONS = {
    "action": {
        "type": "choice",
        "instructions": "What should the day-trading system do right now?",
        "criteria": {
            "buy": "momentum continuation or oversold bounce with high conviction",
            "sell": "overbought or breakdown with high conviction",
            "hold": "no clear edge or mixed signals",
            "exit": "risk limits hit or thesis broken"
        }
    },
    "conviction": {
        "type": "score",
        "instructions": "How strong is the edge?",
        "criteria": ["none", "weak", "moderate", "strong"]
    },
    "skip_due_to_news": {
        "type": "noul",
        "instructions": "Is there material news that makes the technical setup unreliable?"
    },
    "high_gap_risk": {
        "type": "noul",
        "instructions": "Is there elevated risk of a sudden adverse gap?"
    }
}

def decide(state: dict) -> dict:
    """
    Pure System-1 call.
    Returns calibrated probabilities and scores in one forward pass.
    """
    result = router.predict(state, QUESTIONS)

    return {
        "action": result["answers"]["action"]["choice"],
        "probs": result["answers"]["action"]["probabilities"],
        "conviction": result["answers"]["conviction"]["score"],
        "skip_news": result["answers"]["skip_due_to_news"]["noul"],
        "gap_risk": result["answers"]["high_gap_risk"]["noul"],
        "raw": result
    }