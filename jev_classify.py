import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from dotenv import load_dotenv
import pandas as pd
from typesafe_sdk import Choice, Noul, TypeSafeClient
import yt_dlp

# Load variables from .env
load_dotenv()

TYPESAFE_API_KEY = os.getenv("TYPESAFE_API_KEY")
MAX_WORKERS = int(os.getenv("MAX_WORKERS", 8))
OUTPUT_FILE = os.getenv("OUTPUT_FILE", "youtube_jev_classifications.csv")

if not TYPESAFE_API_KEY:
    sys.exit("Error: TYPESAFE_API_KEY is not set in the environment or .env file.")

# ---------------------------------------------------------------------------
# 1. FILE INGESTION & URL CLEANING
# ---------------------------------------------------------------------------

def load_urls_from_file(filepath: str = "urls.txt") -> list[str]:
    """Reads URLs from a text file, skipping blank lines and comments."""
    path = Path(filepath)
    if not path.is_file():
        sys.exit(f"Error: Target URL file '{filepath}' does not exist.")

    with path.open("r", encoding="utf-8") as f:
        urls = [line.strip() for line in f if line.strip() and not line.strip().startswith("#")]
    return urls


def clean_and_canonicalize(urls: list[str]) -> list[str]:
    """Removes duplicates and standardizes watch/shorts links."""
    seen = set()
    cleaned = []

    for raw in urls:
        parsed = urlparse(raw)
        path = parsed.path.rstrip("/")

        # Skip bare domains or homepages
        if not path or path == "/":
            continue

        if "watch" in path:
            video_id = parse_qs(parsed.query).get("v", [None])[0]
            if not video_id:
                continue
            canonical = f"https://www.youtube.com/watch?v={video_id}"
        elif "/shorts/" in path:
            short_id = path.split("/shorts/")[1].split("/")[0]
            canonical = f"https://www.youtube.com/shorts/{short_id}"
        else:
            canonical = f"{parsed.scheme}://{parsed.netloc}{path}"

        if canonical not in seen:
            seen.add(canonical)
            cleaned.append(canonical)

    return cleaned


# ---------------------------------------------------------------------------
# 2. METADATA EXTRACTION
# ---------------------------------------------------------------------------

YDL_OPTS = {
    "quiet": True,
    "no_warnings": True,
    "skip_download": True,
    "extract_flat": True,
}


def fetch_youtube_metadata(url: str) -> dict | None:
    """Extracts lightweight metadata (title, channel, tags, truncated description)."""
    try:
        with yt_dlp.YoutubeDL(YDL_OPTS) as ydl:
            info = ydl.extract_info(url, download=False)
            if not info:
                return None
            return {
                "url": url,
                "title": info.get("title", ""),
                "channel": info.get("channel") or info.get("uploader", ""),
                "description": (info.get("description") or "")[:500].strip(),
                "tags": (info.get("tags") or [])[:6],
            }
    except Exception as e:
        print(f"Failed to fetch metadata for {url}: {e}")
        return None


# ---------------------------------------------------------------------------
# 3. JEV (TYPESAFE) QUESTIONS & CLASSIFICATION
# ---------------------------------------------------------------------------

QUESTIONS = {
    "topic": Choice(
        instructions="What is the primary topic or subject matter of this YouTube video?",
        criteria={
            "tech_and_coding": (
                "Software development, programming, IT, Linux, phone modding, servers, AI, or databases."
            ),
            "gaming_and_lore": (
                "Video game playthroughs, Half-Life/lore analyses, game mods, or gaming culture."
            ),
            "politics_and_society": (
                "Political commentary, government critique, geopolitics, elections, or social debates."
            ),
            "religion_and_spirituality": (
                "Islamic lectures, religious rulings, spirituality, Quranic reflections, or sermons."
            ),
            "history_and_documentary": (
                "Historical events, civilizational narratives, biographies, and historical documentaries."
            ),
            "entertainment_and_comedy": (
                "Short skits, comedy sketches, memes, reactions, or light entertainment."
            ),
            "other": "Miscellaneous or uncategorized topics.",
        },
    ),
    "content_format": Choice(
        instructions="What format is this content presented in?",
        criteria={
            "tutorial_guide": "Step-by-step technical walkthrough or practical how-to guide.",
            "commentary_monologue": "Opinion commentary, podcast monologue, sermon, or political talk.",
            "lore_documentary": "Storytelling, lore explainer, or documentary.",
            "short_form": "Short-form vertical video (YouTube Short), quick tip, or meme.",
            "other": "Other format.",
        },
    ),
    "is_educational": Noul(
        instructions="Does this content primarily teach a skill, concept, historical event, or technical procedure?"
    ),
}


def classify_with_jev(client: TypeSafeClient, metadata: dict) -> dict:
    """Evaluates state against Jev System One questions."""
    state = {
        "title": metadata["title"],
        "channel": metadata["channel"],
        "description": metadata["description"],
        "tags": metadata["tags"],
    }

    response = client.system_one(state=state, questions=QUESTIONS, model="jev-latest")

    topic_ans = response.choices["topic"]
    format_ans = response.choices["content_format"]
    edu_prob = response.nouls["is_educational"].noul

    return {
        "url": metadata["url"],
        "title": metadata["title"],
        "channel": metadata["channel"],
        "topic": topic_ans.choice,
        "topic_confidence": round(topic_ans.confidence, 3),
        "topic_prob": round(topic_ans.probabilities[topic_ans.choice], 3),
        "format": format_ans.choice,
        "format_prob": round(format_ans.probabilities[format_ans.choice], 3),
        "is_educational_prob": round(edu_prob, 3),
    }


# ---------------------------------------------------------------------------
# 4. PIPELINE ORCHESTRATION
# ---------------------------------------------------------------------------

def main():
    raw_urls = load_urls_from_file("urls.txt")
    cleaned_urls = clean_and_canonicalize(raw_urls)
    print(f"Loaded {len(raw_urls)} lines -> {len(cleaned_urls)} valid targets.")

    print(f"Fetching metadata using {MAX_WORKERS} workers...")
    meta_records = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(fetch_youtube_metadata, u): u for u in cleaned_urls}
        for future in as_completed(futures):
            res = future.result()
            if res and res.get("title"):
                meta_records.append(res)

    print(f"Extracted metadata for {len(meta_records)} videos. Running Jev classification...")

    classified_results = []
    with TypeSafeClient(api_key=TYPESAFE_API_KEY) as client:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            future_to_meta = {
                executor.submit(classify_with_jev, client, m): m
                for m in meta_records
            }
            for future in as_completed(future_to_meta):
                try:
                    data = future.result()
                    classified_results.append(data)
                    print(f"[{data['topic']}] ({data['topic_prob']:.2f}) {data['title'][:40]}...")
                except Exception as err:
                    print(f"Classification error: {err}")

    # Export results
    df = pd.DataFrame(classified_results)
    df.to_csv(OUTPUT_FILE, index=False)
    print(f"\nCompleted! Saved results to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()