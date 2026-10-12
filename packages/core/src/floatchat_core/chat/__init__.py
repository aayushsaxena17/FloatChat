"""The conversational flow (PRD section 9.2; ADR-0072, ADR-0073).

classify -> retrieve -> plan -> validate -> execute -> sanitise -> narrate. The model produces a
``stage2-plan-v1`` document (or a clarification, or a refusal) and a bounded narrative; the
validator, the coverage service and the query engine are the authorities.
"""
