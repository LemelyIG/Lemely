"""Provider-neutral model requests (spec 2026-10-19 §1).

``GeminiClient`` builds one :class:`~lemely.io.llm.request.LLMRequest` per attempt
and hands it to the provider its model prefix picks. The client keeps the response
cache, retry, cost ceiling, ledger and ``CallRecord``. Nothing here imports a
provider SDK at module load.
"""
