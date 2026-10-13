"""generate_holdout_dataset.py — Generates dedicated classification holdout dataset.

Stores at least 60 diverse, unseen/novel and adversarial model identities with ground truth
in data/catalog/holdout_dataset.json with ZERO leakage to training.
"""

import json
import os

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOLDOUT_PATH = os.path.join(REPO_ROOT, "data", "catalog", "holdout_dataset.json")

HOLDOUT_SAMPLES = [
    # --- 1. Adversarial & Novel Agentic (Text / Tool / Vision) Models ---
    {"model_id": "anthropic/claude-3-7-sonnet-thought-preview", "expected_agentic": True, "expected_modalities": ["text_chat", "tool_calling"], "category": "novel_agentic"},
    {"model_id": "deepseek-ai/deepseek-vl2-tiny", "expected_agentic": True, "expected_modalities": ["vision", "text_chat", "tool_calling"], "category": "novel_multimodal"},
    {"model_id": "openrouter/auto", "expected_agentic": True, "expected_modalities": ["text_chat", "tool_calling"], "category": "meta_router"},
    {"model_id": "inclusionai/ling-3.0-flash-vl:free", "expected_agentic": True, "expected_modalities": ["vision", "text_chat", "tool_calling"], "category": "novel_multimodal"},
    {"model_id": "google/gemini-2.5-pro-preview-03-25", "expected_agentic": True, "expected_modalities": ["text_chat", "tool_calling", "vision"], "category": "novel_agentic"},
    {"model_id": "mistralai/mistral-large-2411", "expected_agentic": True, "expected_modalities": ["text_chat", "tool_calling"], "category": "agentic_chat"},
    {"model_id": "qwen/qvq-72b-preview", "expected_agentic": True, "expected_modalities": ["vision", "text_chat", "tool_calling"], "category": "reasoning_multimodal"},
    {"model_id": "meta-llama/llama-3.3-70b-instruct", "expected_agentic": True, "expected_modalities": ["text_chat", "tool_calling"], "category": "agentic_chat"},
    {"model_id": "cohere/command-r-plus-08-2024", "expected_agentic": True, "expected_modalities": ["text_chat", "tool_calling"], "category": "agentic_chat"},
    {"model_id": "x-ai/grok-3-beta", "expected_agentic": True, "expected_modalities": ["text_chat", "tool_calling"], "category": "agentic_chat"},
    {"model_id": "01-ai/yi-lightning", "expected_agentic": True, "expected_modalities": ["text_chat", "tool_calling"], "category": "agentic_chat"},
    {"model_id": "zhipu/glm-4-plus", "expected_agentic": True, "expected_modalities": ["text_chat", "tool_calling"], "category": "agentic_chat"},
    {"model_id": "internlm/internlm2_5-20b-chat", "expected_agentic": True, "expected_modalities": ["text_chat", "tool_calling"], "category": "agentic_chat"},
    {"model_id": "baichuan-inc/baichuan-4", "expected_agentic": True, "expected_modalities": ["text_chat", "tool_calling"], "category": "agentic_chat"},
    {"model_id": "minimax/minimax-text-01", "expected_agentic": True, "expected_modalities": ["text_chat", "tool_calling"], "category": "agentic_chat"},
    {"model_id": "stepfun/step-2-16k", "expected_agentic": True, "expected_modalities": ["text_chat", "tool_calling"], "category": "agentic_chat"},
    {"model_id": "deepseek-ai/deepseek-coder-v2.5", "expected_agentic": True, "expected_modalities": ["text_chat", "tool_calling"], "category": "agentic_coding"},
    {"model_id": "qwen/qwen-2.5-coder-32b-instruct", "expected_agentic": True, "expected_modalities": ["text_chat", "tool_calling"], "category": "agentic_coding"},
    {"model_id": "allenai/olmo-2-13b-instruct", "expected_agentic": True, "expected_modalities": ["text_chat", "tool_calling"], "category": "agentic_chat"},
    {"model_id": "tiiuae/falcon-180b-chat", "expected_agentic": True, "expected_modalities": ["text_chat", "tool_calling"], "category": "agentic_chat"},
    {"model_id": "amazon/nova-pro-v1", "expected_agentic": True, "expected_modalities": ["text_chat", "tool_calling", "vision"], "category": "agentic_multimodal"},
    {"model_id": "microsoft/phi-4-mini-instruct", "expected_agentic": True, "expected_modalities": ["text_chat", "tool_calling"], "category": "agentic_chat"},
    {"model_id": "databricks/dbrx-instruct", "expected_agentic": True, "expected_modalities": ["text_chat", "tool_calling"], "category": "agentic_chat"},
    {"model_id": "upstage/solar-pro-preview-instruct", "expected_agentic": True, "expected_modalities": ["text_chat", "tool_calling"], "category": "agentic_chat"},
    {"model_id": "snowflake/arctic-instruct", "expected_agentic": True, "expected_modalities": ["text_chat", "tool_calling"], "category": "agentic_chat"},
    {"model_id": "deepseek-ai/deepseek-r1-zero", "expected_agentic": True, "expected_modalities": ["text_chat", "tool_calling"], "category": "agentic_reasoning"},
    {"model_id": "openai/o3-mini-high", "expected_agentic": True, "expected_modalities": ["text_chat", "tool_calling"], "category": "agentic_reasoning"},
    {"model_id": "google/gemma-3-27b-it", "expected_agentic": True, "expected_modalities": ["text_chat", "tool_calling"], "category": "agentic_chat"},
    {"model_id": "alibabacloud/qwen-omni-turbo", "expected_agentic": True, "expected_modalities": ["vision", "text_chat", "tool_calling"], "category": "agentic_multimodal"},
    {"model_id": "anthropic/claude-3-5-haiku-20241022", "expected_agentic": True, "expected_modalities": ["text_chat", "tool_calling"], "category": "agentic_chat"},

    # --- 2. Non-Agentic Embeddings Models ---
    {"model_id": "amazon/titan-embed-text-v2", "expected_agentic": False, "expected_modalities": ["embeddings"], "category": "embeddings"},
    {"model_id": "openai/text-embedding-3-large", "expected_agentic": False, "expected_modalities": ["embeddings"], "category": "embeddings"},
    {"model_id": "openai/text-embedding-3-small", "expected_agentic": False, "expected_modalities": ["embeddings"], "category": "embeddings"},
    {"model_id": "baai/bge-m3-embeddings", "expected_agentic": False, "expected_modalities": ["embeddings"], "category": "embeddings"},
    {"model_id": "cohere/embed-english-v3.0", "expected_agentic": False, "expected_modalities": ["embeddings"], "category": "embeddings"},
    {"model_id": "cohere/embed-multilingual-v3.0", "expected_agentic": False, "expected_modalities": ["embeddings"], "category": "embeddings"},
    {"model_id": "voyageai/voyage-3-large-embed", "expected_agentic": False, "expected_modalities": ["embeddings"], "category": "embeddings"},
    {"model_id": "nomic-ai/nomic-embed-text-v1.5", "expected_agentic": False, "expected_modalities": ["embeddings"], "category": "embeddings"},
    {"model_id": "intfloat/e5-mistral-7b-instruct-embedding", "expected_agentic": False, "expected_modalities": ["embeddings"], "category": "embeddings"},
    {"model_id": "google/text-embedding-004", "expected_agentic": False, "expected_modalities": ["embeddings"], "category": "embeddings"},

    # --- 3. Non-Agentic Reranker Models ---
    {"model_id": "scale/rerank-v2-turbo", "expected_agentic": False, "expected_modalities": ["rerank"], "category": "rerank"},
    {"model_id": "cohere/rerank-v3.5", "expected_agentic": False, "expected_modalities": ["rerank"], "category": "rerank"},
    {"model_id": "baai/bge-reranker-large", "expected_agentic": False, "expected_modalities": ["rerank"], "category": "rerank"},
    {"model_id": "jinaai/jina-reranker-v2-base-multilingual", "expected_agentic": False, "expected_modalities": ["rerank"], "category": "rerank"},
    {"model_id": "mixedbread-ai/mxbai-rerank-large-v1", "expected_agentic": False, "expected_modalities": ["rerank"], "category": "rerank"},

    # --- 4. Non-Agentic Classification & Safety Guards ---
    {"model_id": "meta-llama/llama-guard-4-12b", "expected_agentic": False, "expected_modalities": ["classification_guard"], "category": "guard"},
    {"model_id": "meta-llama/llama-guard-3-8b", "expected_agentic": False, "expected_modalities": ["classification_guard"], "category": "guard"},
    {"model_id": "openai/omni-moderation-latest", "expected_agentic": False, "expected_modalities": ["classification_guard"], "category": "guard"},
    {"model_id": "google/shieldgemma-9b-safety", "expected_agentic": False, "expected_modalities": ["classification_guard"], "category": "guard"},
    {"model_id": "ibm-granite/granite-guardian-3.1-8b", "expected_agentic": False, "expected_modalities": ["classification_guard"], "category": "guard"},
    {"model_id": "meta/prompt-guard-86m", "expected_agentic": False, "expected_modalities": ["classification_guard"], "category": "guard"},

    # --- 5. Non-Agentic Image Generation Models ---
    {"model_id": "black-forest-labs/flux-1-schnell", "expected_agentic": False, "expected_modalities": ["image_generation"], "category": "image_gen"},
    {"model_id": "black-forest-labs/flux-1-dev", "expected_agentic": False, "expected_modalities": ["image_generation"], "category": "image_gen"},
    {"model_id": "stabilityai/stable-diffusion-3.5-large", "expected_agentic": False, "expected_modalities": ["image_generation"], "category": "image_gen"},
    {"model_id": "openai/dall-e-3", "expected_agentic": False, "expected_modalities": ["image_generation"], "category": "image_gen"},
    {"model_id": "ideogram/ideogram-v2-turbo-canvas", "expected_agentic": False, "expected_modalities": ["image_generation"], "category": "image_gen"},
    {"model_id": "midjourney/midjourney-v6.1", "expected_agentic": False, "expected_modalities": ["image_generation"], "category": "image_gen"},

    # --- 6. Non-Agentic Audio TTS & STT Models ---
    {"model_id": "elevenlabs/multilingual-v2", "expected_agentic": False, "expected_modalities": ["audio_tts"], "category": "audio_tts"},
    {"model_id": "deepgram/aura-orpheus-en", "expected_agentic": False, "expected_modalities": ["audio_tts"], "category": "audio_tts"},
    {"model_id": "playht/play-3.0-mini-speech", "expected_agentic": False, "expected_modalities": ["audio_tts"], "category": "audio_tts"},
    {"model_id": "openai/tts-1-hd", "expected_agentic": False, "expected_modalities": ["audio_tts"], "category": "audio_tts"},
    {"model_id": "openai/whisper-large-v3-turbo", "expected_agentic": False, "expected_modalities": ["audio_stt"], "category": "audio_stt"},
    {"model_id": "deepgram/nova-2-asr", "expected_agentic": False, "expected_modalities": ["audio_stt"], "category": "audio_stt"},
    {"model_id": "distil-whisper/distil-large-v3-stt", "expected_agentic": False, "expected_modalities": ["audio_stt"], "category": "audio_stt"},
    {"model_id": "facebook/seamless-m4t-v2-stt", "expected_agentic": False, "expected_modalities": ["audio_stt"], "category": "audio_stt"}
]


def build_holdout():
    os.makedirs(os.path.dirname(HOLDOUT_PATH), exist_ok=True)
    # Historical expected labels were created in the same static generator as
    # the names and then compared with a name heuristic. They are not an
    # independent gold set. Keep them for auditability, but never treat them as
    # evaluated ground truth until an external reviewer supplies evidence.
    samples = [
        {**sample, "label_status": "legacy_non_independent", "label_evidence": None}
        for sample in HOLDOUT_SAMPLES
    ]
    dataset = {
        "version": "1.1.0",
        "description": "Classifier holdout candidates; legacy labels are not independent ground truth.",
        "holdout_construction": {
            "legacy_row_count": len(samples),
            "legacy_label_source": "Static generator labels; not independently reviewed.",
            "leakage_status": "UNSUITABLE_FOR_PERFORMANCE_ESTIMATION",
            "independent_labeling_required": True,
            "performance_metrics": "NOT MEASURED",
        },
        "total_samples": len(samples),
        "agentic_samples": sum(1 for s in samples if s["expected_agentic"]),
        "non_agentic_samples": sum(1 for s in samples if not s["expected_agentic"]),
        "samples": samples,
        "hard_cases": [
            {"model_id": "unseen-vendor/new-family-27b-tool-preview", "kind": "synthetic_odd_name", "expected_agentic": None},
            {"model_id": "vendor/model-v2.1:free", "kind": "synthetic_pricing_suffix", "expected_agentic": None},
            {"model_id": "vendor/model__INSTRUCT__2027", "kind": "synthetic_delimiter_and_future_version", "expected_agentic": None},
            {"model_id": "vendor/vision-chat-embed-hybrid", "kind": "synthetic_conflicting_modality_tokens", "expected_agentic": None},
            {"model_id": "vendor/guard-chat-72b", "kind": "synthetic_conflicting_guard_and_chat_tokens", "expected_agentic": None},
            {"model_id": "vendor/xyz-9000", "kind": "synthetic_opaque_name", "expected_agentic": None},
            {"model_id": "newvendor/family_4o-mini-2027-09", "kind": "synthetic_unseen_vendor_and_version", "expected_agentic": None},
            {"model_id": "vendor/model (reasoning) [beta]", "kind": "synthetic_punctuation", "expected_agentic": None},
        ],
    }

    with open(HOLDOUT_PATH, "w", encoding="utf-8") as f:
        json.dump(dataset, f, indent=2)

    print(f"Generated {len(samples)} legacy holdout candidates; labels are not independent and metrics are NOT MEASURED.")
    print(f"Saved to: {HOLDOUT_PATH}")


if __name__ == "__main__":
    build_holdout()
