from __future__ import annotations

import base64
import json
from dataclasses import dataclass

import httpx

from app.config import Settings
from app.image_utils import analyze_image
from app.image_utils import clamp_score


@dataclass(slots=True)
class JudgeResult:
    provider: str
    model_name: str
    composition: float
    emotion: float
    story: float
    couple_focus: float
    wedding_mood: float
    positive_comment_1: str
    positive_comment_2: str
    positive_comment_3: str
    improvement_comment: str
    raw_payload: str

    @property
    def total_score(self) -> float:
        return round(
            self.composition
            + self.emotion
            + self.story
            + self.couple_focus
            + self.wedding_mood,
            1,
        )

    @property
    def summary(self) -> str:
        return self.positive_comment_1


def build_judging_prompt(guest_name: str, table_name: str | None) -> str:
    return (
        "You are judging a wedding reception photo contest. Score the photo in five categories from 0 to 20. "
        "Focus on how memorable the photo feels for a live wedding audience, but stay grounded in what is clearly visible. "
        "Evaluate strictly using the full 0-20 scale. Consider 10-12 as the baseline for an average, 'decent' photo. Reserve scores of 18-20 only for truly exceptional shots."
        "The categories are composition, emotion, story, couple_focus, and wedding_mood. "
        "Prefer photos that make the bride and groom look joyful, natural, and central to the moment. "
        "Do not invent gifts, travel, relationships, or scenes that are not clearly shown in the image. "
        "If the bride, groom, or a wedding-related scene is not clearly visible, reflect that honestly in couple_focus and wedding_mood. "
        f"Photographer guest: {guest_name}. Table: {table_name or 'unknown'}. "
        'Return strict JSON with keys "composition", "emotion", "story", "couple_focus", "wedding_mood", '
        '"positive_comment_1", "positive_comment_2", "positive_comment_3", and "improvement_comment". '
        "Each comment must be exactly one short Japanese sentence under 45 characters. "
        "The three positive comments should each praise a different strength when possible. "
        "The improvement comment should describe an honest weak point or missing element in a mild, constructive way. "
        "Strongly adopt the persona of a VERY WITTY, friendly, veteran professional wedding photographer with a DRY, OBSERVANT SENSE OF HUMOR. "
        "Use playful observations, clever analogies, and an engaging but relaxed conversational tone to make the guests chuckle. "
        "Do NOT overuse exclamation marks (!). Keep the tone calm and witty rather than overly excited. End most sentences with a simple period. "
        "All comments must match the score level and must not sound more positive than the score suggests. "
        "Avoid directly mentioning scores. Keep the wording modest, believable, and grounded in what is actually visible."

        "Example of Expected Tone in Japanese (Warm, Witty, Calm, under 45 chars): "
        'positive_comment: "お二人の笑顔が眩しすぎて、式場の照明スタッフが嫉妬しそうな一枚です。"'
        'positive_comment: "この見事な構図を計算して撮ったなら、明日からプロを名乗れます。"'
        'positive_comment: "画面の隅っこで涙ぐむご友人、完全に主役を食うほどの良い表情です。"'
        'improvement_comment: "お二人への愛があふれすぎて、手が少し震えてしまったようです。"'
    )


def parse_result_payload(payload: dict, provider: str, model_name: str) -> JudgeResult:
    return JudgeResult(
        provider=provider,
        model_name=model_name,
        composition=clamp_score(float(payload["composition"])),
        emotion=clamp_score(float(payload["emotion"])),
        story=clamp_score(float(payload["story"])),
        couple_focus=clamp_score(float(payload["couple_focus"])),
        wedding_mood=clamp_score(float(payload["wedding_mood"])),
        positive_comment_1=str(payload["positive_comment_1"]).strip(),
        positive_comment_2=str(payload["positive_comment_2"]).strip(),
        positive_comment_3=str(payload["positive_comment_3"]).strip(),
        improvement_comment=str(payload["improvement_comment"]).strip(),
        raw_payload=json.dumps(payload, ensure_ascii=False, indent=2),
    )


class BaseJudgeProvider:
    provider_name = "base"

    def __init__(self, settings: Settings, model_name: str | None = None) -> None:
        self.settings = settings
        self.model_name = model_name or "unknown"

    @property
    def display_name(self) -> str:
        return f"{self.provider_name}:{self.model_name}"

    def judge(
        self,
        image_bytes: bytes,
        mime_type: str,
        guest_name: str,
        table_name: str | None,
    ) -> JudgeResult:
        raise NotImplementedError


class MockJudgeProvider(BaseJudgeProvider):
    provider_name = "mock"

    def __init__(self, settings: Settings, model_name: str | None = None) -> None:
        super().__init__(settings, model_name or "local-heuristic-v1")

    def judge(
        self,
        image_bytes: bytes,
        mime_type: str,
        guest_name: str,
        table_name: str | None,
    ) -> JudgeResult:
        metrics = analyze_image(image_bytes)
        hash_bias = int(metrics.sha256[:2], 16) / 255.0

        composition = clamp_score(8 + (metrics.contrast / 10.0) + (metrics.sharpness / 20.0))
        emotion = clamp_score(7 + (metrics.brightness / 22.0) + hash_bias)
        story = clamp_score(6 + (metrics.entropy * 1.7))
        couple_focus = clamp_score(7 + (metrics.sharpness / 18.0) + (metrics.brightness / 30.0))
        wedding_mood = clamp_score(8 + (metrics.saturation / 18.0) + (metrics.brightness / 24.0))

        top_axes = sorted(
            [
                ("構図", composition),
                ("表情", emotion),
                ("物語性", story),
                ("主役感", couple_focus),
                ("祝祭感", wedding_mood),
            ],
            key=lambda item: item[1],
            reverse=True,
        )
        positive_comment_1 = f"{top_axes[0][0]}の見せ方が安定しています。"
        positive_comment_2 = f"{top_axes[1][0]}が自然に伝わる一枚です。"
        positive_comment_3 = f"{top_axes[2][0]}にも印象が残ります。"
        improvement_comment = f"{top_axes[-1][0]}はもう一歩伸びしろがあります。"

        payload = {
            "composition": composition,
            "emotion": emotion,
            "story": story,
            "couple_focus": couple_focus,
            "wedding_mood": wedding_mood,
            "positive_comment_1": positive_comment_1,
            "positive_comment_2": positive_comment_2,
            "positive_comment_3": positive_comment_3,
            "improvement_comment": improvement_comment,
            "provider_note": "Scored locally with deterministic image heuristics.",
            "mime_type": mime_type,
        }
        return parse_result_payload(payload, self.provider_name, self.model_name)


class GeminiJudgeProvider(BaseJudgeProvider):
    provider_name = "gemini"

    def __init__(self, settings: Settings, model_name: str | None = None) -> None:
        super().__init__(settings, model_name or settings.google_model)

    def judge(
        self,
        image_bytes: bytes,
        mime_type: str,
        guest_name: str,
        table_name: str | None,
    ) -> JudgeResult:
        if not self.settings.google_api_key:
            raise RuntimeError("GOOGLE_API_KEY is not configured.")

        prompt = build_judging_prompt(guest_name, table_name)
        image_b64 = base64.b64encode(image_bytes).decode("ascii")
        response = httpx.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{self.model_name}:generateContent",
            params={"key": self.settings.google_api_key},
            json={
                "systemInstruction": {
                    "parts": [
                        {
                            "text": "Judge photos fairly and return only strict JSON.",
                        }
                    ]
                },
                "contents": [
                    {
                        "role": "user",
                        "parts": [
                            {"text": prompt},
                            {
                                "inline_data": {
                                    "mime_type": mime_type,
                                    "data": image_b64,
                                }
                            },
                        ],
                    }
                ],
                "generationConfig": {
                    "temperature": 0.1,
                    "responseMimeType": "application/json",
                },
            },
            timeout=60,
        )
        response.raise_for_status()
        payload = response.json()
        text = payload["candidates"][0]["content"]["parts"][0]["text"]
        return parse_result_payload(json.loads(text), self.provider_name, self.model_name)


class OllamaJudgeProvider(BaseJudgeProvider):
    provider_name = "ollama"

    def __init__(self, settings: Settings, model_name: str | None = None) -> None:
        super().__init__(settings, model_name or settings.ollama_model)

    def judge(
        self,
        image_bytes: bytes,
        mime_type: str,
        guest_name: str,
        table_name: str | None,
    ) -> JudgeResult:
        prompt = build_judging_prompt(guest_name, table_name)
        image_b64 = base64.b64encode(image_bytes).decode("ascii")
        response = httpx.post(
            f"{self.settings.ollama_base_url.rstrip('/')}/api/chat",
            json={
                "model": self.model_name,
                "stream": False,
                "format": "json",
                "messages": [
                    {
                        "role": "system",
                        "content": "Judge wedding photos and return only strict JSON.",
                    },
                    {
                        "role": "user",
                        "content": prompt,
                        "images": [image_b64],
                    },
                ],
            },
            timeout=120,
        )
        response.raise_for_status()
        payload = response.json()
        return parse_result_payload(
            json.loads(payload["message"]["content"]),
            self.provider_name,
            self.model_name,
        )


def build_provider(settings: Settings, preference: str | None, model_hint: str | None) -> BaseJudgeProvider:
    selected = (preference or settings.ai_provider or "auto").lower()
    if selected == "auto":
        if settings.google_api_key:
            return GeminiJudgeProvider(settings, model_hint or settings.google_model)
        return MockJudgeProvider(settings, model_hint)
    if selected == "gemini":
        return GeminiJudgeProvider(settings, model_hint or settings.google_model)
    if selected == "ollama":
        return OllamaJudgeProvider(settings, model_hint or settings.ollama_model)
    return MockJudgeProvider(settings, model_hint)


def provider_options() -> list[str]:
    return ["auto", "mock", "gemini", "ollama"]
