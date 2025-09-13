from __future__ import annotations

import json
from typing import Any, Dict, Optional

from tenacity import retry, wait_exponential, stop_after_attempt
from openai import OpenAI, BadRequestError, NotFoundError

from .decisions import validate_decision, Decision


class ChatClient:
    def __init__(self, api_key: Optional[str], model: str, temperature: float, system_prompt_path: str):
        self.client = OpenAI(api_key=api_key)
        self.model = model
        self.temperature = temperature
        with open(system_prompt_path, "r", encoding="utf-8") as f:
            self.system_prompt = f.read()

    @retry(wait=wait_exponential(multiplier=1, min=1, max=8), stop=stop_after_attempt(3))
    def _ask(self, user_payload_json: str) -> str:
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_payload_json},
        ]
        # First attempt: as configured
        try:
            if str(self.model).startswith("gpt-5-"):
                resp = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    response_format={"type": "json_object"},
                )
            else:
                resp = self.client.chat.completions.create(
                    model=self.model,
                    temperature=self.temperature,
                    messages=messages,
                    response_format={"type": "json_object"},
                )
            return resp.choices[0].message.content or ""
        except BadRequestError as e:
            msg = str(e)
            # Retry without temperature if model forbids it
            if "temperature" in msg.lower():
                resp = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    response_format={"type": "json_object"},
                )
                return resp.choices[0].message.content or ""
            # Fallback to default model if bad request indicates model issues
            if "model" in msg.lower() or "not found" in msg.lower():
                fallback_model = "gpt-4o-mini"
                resp = self.client.chat.completions.create(
                    model=fallback_model,
                    messages=messages,
                    response_format={"type": "json_object"},
                )
                return resp.choices[0].message.content or ""
            raise
        except NotFoundError:
            # Model not found -> fallback
            fallback_model = "gpt-4o-mini"
            resp = self.client.chat.completions.create(
                model=fallback_model,
                messages=messages,
                response_format={"type": "json_object"},
            )
            return resp.choices[0].message.content or ""

    def decide(self, payload: Dict[str, Any], remaining_info_requests: int) -> Decision:
        user_json = json.dumps(payload, ensure_ascii=False)
        first = self._ask(user_json)
        try:
            obj = json.loads(first)
            return validate_decision(obj, remaining_info_requests)
        except Exception:
            # one retry with strict hint
            hint_payload = {
                "_hint": "верни валидный JSON без пояснений",
                **payload,
            }
            user_json2 = json.dumps(hint_payload, ensure_ascii=False)
            second = self._ask(user_json2)
            try:
                obj2 = json.loads(second)
                return validate_decision(obj2, remaining_info_requests)
            except Exception:
                # fallback to do_nothing
                return Decision(action="do_nothing", idempotency_key="fallback-do-nothing", params={})
