"""The A/B harness (feature 007): run one campaign under two arms and compare the outcomes.

This package adds the campaign/arm/experiment layer on top of features 002-005: the engine replays the existing
run path (`kestrel.runs`) for each arm, `stats`/`pricing`/`results` aggregate the stored runs into an honest
comparison, and `kestrel.report.experiment` renders it. No attack content lives here - behaviour only.
"""
