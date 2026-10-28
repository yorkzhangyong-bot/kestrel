"""The OWASP-mapped, fix-ready report (feature 005), realising constitution Principle VI.

Built as a pure function over data features 001-004 already stored: `model.build_report` assembles a ReportModel
from a target and its runs/turns, `render` turns it into Markdown and escaped, self-contained HTML, and `recommend`
supplies model-generated fix suggestions (via the judge client), cached per run id. The report reads only; it starts
no attack, sends nothing to a target, and never writes to the experience store. No attack text lives in this code.
"""
