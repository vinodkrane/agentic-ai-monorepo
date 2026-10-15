"""Bedrock model wrapper so deepeval can use Claude on Bedrock as the judge
instead of calling OpenAI (we are not allowed to send docs outside AWS)."""
from deepeval.models import DeepEvalBaseLLM
from langchain_aws import ChatBedrockConverse

from app import config


class BedrockJudge(DeepEvalBaseLLM):
    def __init__(self, model_id=config.JUDGE_MODEL_ID):
        self.model_id = model_id
        self.model = None

    def load_model(self):
        if self.model is None:
            self.model = ChatBedrockConverse(
                model=self.model_id,
                region_name=config.AWS_REGION,
                temperature=0,
                max_tokens=2000,
            )
        return self.model

    def generate(self, prompt):
        return self.load_model().invoke(prompt).content

    async def a_generate(self, prompt):
        resp = await self.load_model().ainvoke(prompt)
        return resp.content

    def get_model_name(self):
        return f"bedrock:{self.model_id}"
