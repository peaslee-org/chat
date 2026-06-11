import asyncio
import json
import logging

import boto3
import botocore.exceptions
from fastapi import HTTPException
from langsmith import get_current_run_tree, traceable

from app.config import get_settings

logger = logging.getLogger(__name__)


def _fetch_prices(region: str) -> dict[str, dict[str, float]]:
    """Query the AWS Price List API for Bedrock on-demand token prices.

    Returns a dict keyed by human-readable model name (matching modelName from
    list_foundation_models), e.g. {"Claude 3 Sonnet": {"input": 0.003, "output": 0.015}}.
    Pricing client must always target us-east-1 regardless of the Bedrock region.
    Fails gracefully — returns an empty dict if the call fails or lacks IAM permission.
    """
    try:
        pricing_client = boto3.client("pricing", region_name="us-east-1")
        paginator = pricing_client.get_paginator("get_products")
        pages = paginator.paginate(
            ServiceCode="AmazonBedrock",
            Filters=[
                {"Type": "TERM_MATCH", "Field": "regionCode", "Value": region},
                {"Type": "TERM_MATCH", "Field": "feature", "Value": "On-demand Inference"},
            ],
        )

        prices: dict[str, dict[str, float]] = {}
        for page in pages:
            for raw in page["PriceList"]:
                item = json.loads(raw)
                attrs = item.get("product", {}).get("attributes", {})
                model_name = attrs.get("model") or attrs.get("titanModel")
                if not model_name:
                    continue
                inference_type = attrs.get("inferenceType", "").lower()
                if "cache" in inference_type:
                    continue
                if "input" in inference_type:
                    direction = "input"
                elif "output" in inference_type:
                    direction = "output"
                else:
                    continue
                on_demand = item.get("terms", {}).get("OnDemand", {})
                for term in on_demand.values():
                    for dim in term.get("priceDimensions", {}).values():
                        if dim.get("unit") == "1K tokens":
                            price_str = dim["pricePerUnit"].get("USD")
                            if price_str:
                                prices.setdefault(model_name, {})[direction] = float(price_str)
        return prices
    except Exception:
        logger.warning("Failed to fetch Bedrock pricing from AWS Price List API", exc_info=True)
        return {}


class BedrockService:
    def __init__(self):
        settings = get_settings()
        self._region = settings.aws_region
        self._client = boto3.client("bedrock-runtime", region_name=self._region)
        self._model_id = settings.bedrock_model_id

    @traceable(run_type="llm", name="bedrock-invoke")
    async def invoke(self, messages: list[dict], system: str = "", model_id: str | None = None) -> str:
        effective_model = model_id or self._model_id
        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 4096,
            "messages": messages,
        }
        if system:
            body["system"] = system

        def _sync_invoke():
            response = self._client.invoke_model(
                modelId=effective_model,
                body=json.dumps(body),
            )
            return json.loads(response["body"].read())

        try:
            result = await asyncio.to_thread(_sync_invoke)
        except botocore.exceptions.ClientError as exc:
            error_code = exc.response["Error"]["Code"]
            error_msg = exc.response["Error"]["Message"]
            logger.error("Bedrock invoke_model failed [%s]: %s", error_code, error_msg)
            if error_code in ("ResourceNotFoundException", "AccessDeniedException"):
                raise HTTPException(status_code=503, detail=f"Model unavailable: {error_msg}")
            raise HTTPException(status_code=502, detail=f"Bedrock error [{error_code}]: {error_msg}")

        run = get_current_run_tree()
        if run:
            run.metadata["ls_model_name"] = effective_model
            run.metadata["ls_provider"] = "amazon_bedrock"
            usage = result.get("usage", {})
            if usage:
                input_tokens = usage.get("input_tokens", 0)
                output_tokens = usage.get("output_tokens", 0)
                run.add_outputs({
                    "usage": {
                        "prompt_tokens": input_tokens,
                        "completion_tokens": output_tokens,
                        "total_tokens": input_tokens + output_tokens,
                    }
                })

        return result["content"][0]["text"]

    async def list_models(self) -> list[dict]:
        def _sync_list():
            bedrock_client = boto3.client("bedrock", region_name=self._region)

            profiles = bedrock_client.list_inference_profiles(
                typeEquals="SYSTEM_DEFINED",
            ).get("inferenceProfileSummaries", [])

            foundation_models = bedrock_client.list_foundation_models(
                byOutputModality="TEXT",
                byInferenceType="ON_DEMAND",
            ).get("modelSummaries", [])
            fm_by_id = {m["modelId"]: m for m in foundation_models}

            prices = _fetch_prices(self._region)

            results = []
            for p in profiles:
                profile_id = p["inferenceProfileId"]
                # Strip geographic prefix (e.g. "us.", "eu.", "ap.") to get the base model ID
                base_model_id = profile_id.split(".", 1)[1] if "." in profile_id else profile_id
                fm = fm_by_id.get(base_model_id)
                if fm is None:
                    continue
                results.append({
                    "model_id": profile_id,
                    "model_name": fm["modelName"],
                    "provider_name": fm["providerName"],
                    "input_price_per_1k_tokens": prices.get(fm["modelName"], {}).get("input"),
                    "output_price_per_1k_tokens": prices.get(fm["modelName"], {}).get("output"),
                })
            return results

        return await asyncio.to_thread(_sync_list)


class MockBedrockService:
    def __init__(self, delay: float = 0.0):
        self._delay = delay

    async def invoke(self, messages: list[dict], system: str = "", model_id: str | None = None) -> str:
        if self._delay > 0:
            logger.debug("MockBedrockService: thinking... (%.1fs delay)", self._delay)
            await asyncio.sleep(self._delay)

        last_user_message = next(
            (m["content"] for m in reversed(messages) if m["role"] == "user"), ""
        )
        return f"[mock] Echo: {last_user_message}"

    async def list_models(self) -> list[dict]:
        return [
            {"model_id": "anthropic.claude-3-sonnet-20240229-v1:0", "model_name": "Claude 3 Sonnet", "provider_name": "Anthropic", "input_price_per_1k_tokens": 0.003, "output_price_per_1k_tokens": 0.015},
            {"model_id": "anthropic.claude-3-haiku-20240307-v1:0", "model_name": "Claude 3 Haiku", "provider_name": "Anthropic", "input_price_per_1k_tokens": 0.00025, "output_price_per_1k_tokens": 0.00125},
        ]


def get_bedrock_service() -> BedrockService | MockBedrockService:
    settings = get_settings()
    if settings.use_mock_bedrock:
        return MockBedrockService(delay=settings.mock_bedrock_delay_seconds)
    return BedrockService()
