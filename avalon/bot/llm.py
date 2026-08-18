from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Callable, Optional, Tuple, cast

from ..config import SETTINGS

logger = logging.getLogger(__name__)


@dataclass
class ExtractionResult:
    success: bool
    value: Any
    error: Optional[str] = None


class LLMClient:
    def __init__(self, model_id: str | None = None) -> None:
        self.model_id = model_id or SETTINGS.qwen_model
        # Lazily populated on first use; Any so mypy --strict accepts the model
        # and tokenizer objects (rather than inferring the attribute type None).
        self._model: Any = None
        self._tokenizer: Any = None

    def _ensure_loaded(self) -> Tuple[Any, Any]:
        if self._model is None or self._tokenizer is None:
            from mlx_lm import load

            # load() returns (model, tokenizer), or a 3-tuple when return_config
            # is set — which we never do. cast pins it to the pair we unpack so
            # the typed mlx_lm union doesn't trip the strict gate.
            self._model, self._tokenizer = cast(Tuple[Any, Any], load(self.model_id))
        return self._model, self._tokenizer

    def generate(self, prompt: str, max_tokens: int = 512, temperature: float = 0.4) -> str:
        """Generate raw text from the LLM."""
        model, tokenizer = self._ensure_loaded()
        from mlx_lm import generate
        from mlx_lm.sample_utils import make_sampler

        sampler = make_sampler(temp=temperature)
        text: str = generate(
            model,
            tokenizer,
            prompt=prompt,
            max_tokens=max_tokens,
            sampler=sampler,
        )
        return text

    def generate_with_retry(
        self,
        prompt: str,
        extractor: Callable[[str], ExtractionResult],
        max_retries: int = 3,
        max_tokens: int = 512,
        base_temperature: float = 0.4,
    ) -> ExtractionResult:
        """Generate with retry logic, re-prompting with error feedback on failure."""
        current_prompt = prompt
        temperature = base_temperature

        for attempt in range(max_retries):
            logger.debug(f"LLM attempt {attempt + 1}/{max_retries}, temp={temperature:.2f}")
            text = self.generate(current_prompt, max_tokens=max_tokens, temperature=temperature)
            logger.debug(f"LLM response: {text[:200]}...")

            result = extractor(text)
            if result.success:
                return result

            logger.warning(f"Extraction failed (attempt {attempt + 1}): {result.error}")

            # Build retry prompt with error feedback
            current_prompt = (
                f"{prompt}\n\n"
                f"[你之前的回复无效：{result.error}]\n"
                f"请严格按照格式重新回答。"
            )
            # Slightly increase temperature on retry
            temperature = min(0.8, temperature + 0.15)

        return ExtractionResult(
            success=False, value=None, error=f"重试 {max_retries} 次后仍然失败"
        )

    # --- Extraction methods for the new simple format ---

    @staticmethod
    def extract_team(text: str) -> ExtractionResult:
        """Extract team names from 'TEAM: Name1, Name2' format."""
        # Look for TEAM: followed by comma-separated names. The separator is
        # horizontal whitespace only ([^\S\n]) so an empty "TEAM:" line cannot
        # reach across the newline and capture the following line as the roster.
        match = re.search(r"TEAM:[^\S\n]*([^\n]*)", text, re.IGNORECASE)
        if not match:
            return ExtractionResult(success=False, value=None, error="未找到 'TEAM:' 行")

        names_str = match.group(1).strip()
        if not names_str:
            return ExtractionResult(success=False, value=None, error="TEAM: 行为空")

        # Split by comma and clean up names
        names = [name.strip() for name in names_str.split(",") if name.strip()]
        if not names:
            return ExtractionResult(success=False, value=None, error="TEAM: 行中没有有效名字")

        return ExtractionResult(success=True, value=names)

    @staticmethod
    def extract_vote(text: str) -> ExtractionResult:
        """Extract vote from 'VOTE: APPROVE' or 'VOTE: REJECT' format."""
        match = re.search(r"VOTE:\s*(APPROVE|REJECT)", text, re.IGNORECASE)
        if not match:
            return ExtractionResult(
                success=False, value=None, error="未找到 'VOTE: APPROVE' 或 'VOTE: REJECT'"
            )

        vote = match.group(1).upper()
        return ExtractionResult(success=True, value=vote == "APPROVE")

    @staticmethod
    def extract_quest(text: str) -> ExtractionResult:
        """Extract quest vote from 'QUEST: SUCCESS' or 'QUEST: FAIL' format."""
        match = re.search(r"QUEST:\s*(SUCCESS|FAIL)", text, re.IGNORECASE)
        if not match:
            return ExtractionResult(
                success=False, value=None, error="未找到 'QUEST: SUCCESS' 或 'QUEST: FAIL'"
            )

        quest = match.group(1).upper()
        return ExtractionResult(success=True, value=quest == "SUCCESS")

    @staticmethod
    def extract_say(text: str) -> ExtractionResult:
        """Extract chat message from 'SAY: message' format."""
        # Horizontal-whitespace separator keeps an empty "SAY:" line from
        # capturing whatever the model wrote on the next line.
        match = re.search(r"SAY:[^\S\n]*([^\n]*)", text, re.IGNORECASE)
        if not match:
            return ExtractionResult(success=False, value=None, error="未找到 'SAY:' 行")

        message = match.group(1).strip()
        if not message:
            return ExtractionResult(success=False, value=None, error="SAY: 行为空")

        # Clean up the message - remove quotes if present
        if message.startswith('"') and message.endswith('"'):
            message = message[1:-1]
        if message.startswith("'") and message.endswith("'"):
            message = message[1:-1]

        # Remove any action keywords that leaked into the message
        # These patterns match action formats that shouldn't be in chat
        action_patterns = [
            r"\s*VOTE:\s*(APPROVE|REJECT).*$",
            r"\s*QUEST:\s*(SUCCESS|FAIL).*$",
            r"\s*TEAM:\s*[^\n]*$",
            r"\s*TARGET:\s*[^\n]*$",
            r"\s*INSPECT:\s*[^\n]*$",
        ]
        for pattern in action_patterns:
            message = re.sub(pattern, "", message, flags=re.IGNORECASE).strip()

        if not message:
            return ExtractionResult(
                success=False, value=None, error="SAY: 行只包含操作关键字"
            )

        return ExtractionResult(success=True, value=message)

    @staticmethod
    def extract_target(text: str, keyword: str = "TARGET") -> ExtractionResult:
        """Extract target name from 'TARGET: Name' or 'INSPECT: Name' format."""
        # Horizontal-whitespace separator: an empty "TARGET:"/"INSPECT:" line
        # must not capture the next line (e.g. a trailing SAY) as the target.
        pattern = rf"{keyword}:[^\S\n]*([^\n]*)"
        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
            return ExtractionResult(success=False, value=None, error=f"未找到 '{keyword}:' 行")

        name = match.group(1).strip()
        if not name:
            return ExtractionResult(success=False, value=None, error=f"{keyword}: 行为空")

        return ExtractionResult(success=True, value=name)
