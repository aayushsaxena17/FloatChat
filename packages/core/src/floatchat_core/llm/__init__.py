"""LLM provider abstraction (PRD section 5.11; ADR-0070).

The query engine never imports a vendor SDK. Adapters are thin REST clients behind one
interface; ``policy.ResilientProvider`` adds timeouts, retries, the circuit breaker, the daily
caps and the call ledger. The model's output is untrusted input to the plan validator.
"""
