import json
import os
import sys
import time

from dotenv import dotenv_values
from google import genai
from google.genai import errors as genai_errors
from google.genai import types

# Add parent directory (project root) to sys.path for importing system_prompt
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from system_prompt import SYSTEM_PROMPT  # noqa: E402

# Fix encoding for Windows terminal (cmd/powershell)
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore

STATE_FILE = os.path.join(os.path.dirname(__file__), "state_gemini.json")
SAMPLE_QUESTION = "How do I connect google meet?"
# Model fallback in priority order (same free-tier quota pool, usually resets daily)
MODEL_PREFERENCE = [
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
]
MAX_RETRIES = 2


def main():
    # Read API key from .env file
    env_path = os.path.join(os.path.dirname(__file__), "..", ".env.sample")
    env_vars = dotenv_values(env_path)

    api_key = env_vars.get("GEMINI_API_KEY")
    if not api_key:
        raise SystemExit("GEMINI_API_KEY not found in .env.sample.")

    # Read state to get store_name and model
    if not os.path.exists(STATE_FILE):
        raise SystemExit(
            f"{STATE_FILE} not found. "
            "Please run vector_store_gemini.py first."
        )
    with open(STATE_FILE) as f:
        state = json.load(f)

    store_name = state.get("store_name")
    if not store_name:
        raise SystemExit("store_name not found in state_gemini.json.")

    model = state.get("model", "gemini-2.5-flash")

    client = genai.Client(api_key=api_key)

    print(f"Store        : {store_name}")
    print(f"Model        : {model}")
    print(f"Question     : {SAMPLE_QUESTION}")
    print("-" * 60)

    # Configure FileSearch Tool pointing to the uploaded store
    file_search_tool = types.Tool(
        file_search=types.FileSearch(
            file_search_store_names=[store_name],
        )
    )

    # Try each preferred model in order (to avoid 429 free-tier limits)
    model_to_use = state.get("model", MODEL_PREFERENCE[0])
    all_models = MODEL_PREFERENCE if model_to_use not in MODEL_PREFERENCE else [model_to_use] + [m for m in MODEL_PREFERENCE if m != model_to_use]

    response = None
    for model_name in all_models:
        daily_exhausted = False
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                print(f"[retry] Model={model_name}, attempt {attempt}/{MAX_RETRIES}...")
                response = client.models.generate_content(
                    model=model_name,
                    contents=SAMPLE_QUESTION,
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_PROMPT,
                        tools=[file_search_tool],
                        temperature=0.2,
                    ),
                )
                print(f"[ok] Model {model_name} responded.")
                break  # Success
            except Exception as e:
                err_str = str(e)
                is_429 = "429" in err_str or "RESOURCE_EXHAUSTED" in err_str
                is_daily = "PerDay" in err_str or "limit: 0" in err_str

                if is_429:
                    if is_daily:
                        # Daily quota fully exhausted, retrying is pointless — try next model
                        print(f"[daily-limit] Model {model_name}: daily quota exhausted. Trying next model...")
                        daily_exhausted = True
                        break
                    else:
                        # Temporary rate limit, wait and retry
                        retry_wait = 60 * attempt
                        print(f"[429] Temporary rate limit. Waiting {retry_wait}s before retrying...")
                        time.sleep(retry_wait)
                elif "404" in err_str or "NOT_FOUND" in err_str:
                    # Model not found in this API version, skip to next
                    print(f"[404] Model {model_name} not found, trying next model...")
                    daily_exhausted = True  # Use this flag to skip to the next model
                    break
                else:
                    raise
        if response:
            break
        if not daily_exhausted:
            # Error is not a daily limit issue, stop entirely
            break

    if not response:
        raise SystemExit(
            "All models are rate-limited or daily quota exhausted.\n"
            "Please check: https://ai.dev/rate-limit\n"
            "Or wait 24h for the daily quota to reset."
        )

    # Print the answer
    print("\nOptiBot (Gemini) Response:\n")
    print(response.text)

    # Print citations if available
    if response.candidates:
        candidate = response.candidates[0]
        if hasattr(candidate, "grounding_metadata") and candidate.grounding_metadata:
            gm = candidate.grounding_metadata
            if hasattr(gm, "grounding_chunks") and gm.grounding_chunks:
                print("\n-- Citations (Grounding Chunks) --")
                for i, chunk in enumerate(gm.grounding_chunks, 1):
                    if hasattr(chunk, "retrieved_context") and chunk.retrieved_context:
                        ctx = chunk.retrieved_context
                        title = getattr(ctx, "title", "N/A")
                        uri = getattr(ctx, "uri", "N/A")
                        print(f"  [{i}] {title}")
                        if uri and uri != "N/A":
                            print(f"      URI: {uri}")
            elif hasattr(gm, "retrieval_metadata") and gm.retrieval_metadata:
                print(f"\n-- Retrieval Metadata --")
                print(f"  {gm.retrieval_metadata}")
            else:
                print("\n(No grounding chunks found in the response)")
        else:
            # Fallback: print finish_reason
            finish_reason = getattr(candidate, "finish_reason", "N/A")
            print(f"\n(finish_reason: {finish_reason} — grounding_metadata not present in response)")


if __name__ == "__main__":
    main()
