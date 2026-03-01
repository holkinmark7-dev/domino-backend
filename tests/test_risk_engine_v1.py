from routers.services.risk_engine import map_score_to_escalation, ESCALATION_ORDER


def test_score_mapping_table():
    cases = [
        (0, "LOW"),
        (1, "LOW"),
        (2, "MODERATE"),
        (3, "MODERATE"),
        (4, "HIGH"),
        (5, "HIGH"),
        (6, "CRITICAL"),
        (8, "CRITICAL"),
    ]

    for score, expected in cases:
        assert map_score_to_escalation(score) == expected


def test_escalation_order_monotonic():
    order = ESCALATION_ORDER

    for lower in order:
        for higher in order:
            if order[higher] >= order[lower]:
                assert order[higher] >= order[lower]
