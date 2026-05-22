from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError

from lemely.core.loose_schemas import MarkScheme
from lemely.io.prompts.mark_scheme_parsing import PARSER_SYSTEM_PROMPT, PARSER_USER_PROMPT


class GeminiMarkSchemeParser:
    def __init__(
        self,
        *,
        model: str = "gemini-2.5-flash",
        raw_output_dir: str | Path | None = None,
        max_output_tokens: int = 65536,
    ) -> None:
        self.model = model
        self.raw_output_dir = Path(raw_output_dir) if raw_output_dir is not None else None
        self.max_output_tokens = max_output_tokens

    def _raw_output_path(self, pdf_path: Path) -> Path:
        if self.raw_output_dir is None:
            return pdf_path.with_suffix(".raw.json")
        self.raw_output_dir.mkdir(parents=True, exist_ok=True)
        return self.raw_output_dir / f"{pdf_path.stem}.raw.json"

    def __call__(self, pdf_path: Path) -> MarkScheme:
        from google import genai
        from google.genai import types

        client = genai.Client()
        uploaded = client.files.upload(file=pdf_path)
        response = client.models.generate_content(
            model=self.model,
            config=types.GenerateContentConfig(
                max_output_tokens=self.max_output_tokens,
                thinking_config=types.ThinkingConfig(thinking_budget=0),
                response_mime_type="application/json",
                response_schema=MarkScheme.model_json_schema(),
                system_instruction=PARSER_SYSTEM_PROMPT,
            ),
            contents=[PARSER_USER_PROMPT, uploaded],  # type: ignore[arg-type]
        )

        raw_text = response.text or ""
        self._raw_output_path(pdf_path).write_text(raw_text, encoding="utf-8")
        finish_reason = response.candidates[0].finish_reason if response.candidates else None
        if finish_reason == types.FinishReason.MAX_TOKENS:
            raise RuntimeError(
                f"Gemini hit max_output_tokens for {pdf_path}; raw partial JSON was saved."
            )

        try:
            return MarkScheme.model_validate_json(raw_text)
        except ValidationError as exc:
            raise RuntimeError(
                f"Gemini returned output that did not validate against MarkScheme for {pdf_path}."
            ) from exc
