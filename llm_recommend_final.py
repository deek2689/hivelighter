import json
import boto3
import pymongo
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# MongoDB setup
MONGO_URI = os.getenv("MONGODB_URI")
client = pymongo.MongoClient(MONGO_URI)
db = client["techcrunch_db"]
stories = db["top_stories"]

# AWS Bedrock client
bedrock = boto3.client("bedrock-runtime", region_name="us-east-1")
model_id = "us.anthropic.claude-3-5-sonnet-20241022-v2:0"

# Load user preference data
#with open('/home/enas/Downloads/user_data.json', 'r') as file:
    #articles = json.load(file)
    
    
# Load user preference data
with open('/home/enas/Downloads/user_data.json', 'r') as file:
    articles = json.load(file)

# Connect to vault collection
vault = db["vault"]

# ===> Extract summaries and response arrays
article_titles = [article["title"] for article in articles]

summaries = []
response_arrays = []

for title in article_titles:
    doc = vault.find_one({"title": title}, {"summary": 1, "response_array": 1})
    if doc:
        summaries.append({
            "title": title,
            "summary": doc.get("summary", ""),
            "response_array": doc.get("response_array", [])
        })

# You can now use `summaries` for advanced prompting, fine-tuning, or analysis later



score_map = {
    1: "strong accept (liked)",
    0: "weak accept (neutral)",
    -1: "reject (disliked)"
}



user_name = articles[0].get("user_name", "The user")
formatted_rated = [
    f'- "{a["title"]}" — Score: {score_map.get(a["score"], "unknown")}, Rank: {a.get("rank_position", "N/A")}'
    for a in articles
]

rated_block = "\n".join(formatted_rated)

# ===> Fetch top story titles from MongoDB
#candidate_articles = list(stories.find({}, {"title": 1, "_id": 0}))
#candidate_titles = [article["title"] for article in candidate_articles if article.get("title")]
#candidate_block = "\n".join([f"- {title}" for title in candidate_titles])


# ===> Fetch top story titles from MongoDB
# candidate_articles = list(stories.find({}, {"title": 1, "_id": 0}))
# candidate_titles = [article["title"] for article in candidate_articles if article.get("title")]
# candidate_block = "\n".join([f"- {title}" for title in candidate_titles])

from datetime import datetime, timedelta, time
import pytz  # Or from zoneinfo import ZoneInfo if using Python 3.9+
from pymongo import DESCENDING

utc = pytz.UTC  # Adjust if you're using a different timezone

# Step 1: Get the latest article
latest_article = stories.find_one(
    {"published": {"$exists": True}}, 
    sort=[("published", DESCENDING)]
)

if latest_article and "published" in latest_article:
    latest_date = latest_article["published"].date()
    day_before = latest_date - timedelta(days=1)

    # Step 2: Filter articles within date range
    start_dt = utc.localize(datetime.combine(day_before, time.min))
    end_dt = utc.localize(datetime.combine(latest_date, time.max))

    filtered_articles = stories.find(
        {
            "published": {
                "$gte": start_dt,
                "$lte": end_dt
            }
        },
        {"title": 1, "published": 1, "summary": 1, "response_array": 1, "_id": 0}
    )

    filtered_articles = list(filtered_articles)

    # Step 3: Build mapping with optional summary / response_array
    title_to_published = {}
    candidate_lines = []

    for article in filtered_articles:
        title = article.get("title", "Untitled")
        published = article.get("published")
        summary = article.get("summary", "").strip()
        response_array = article.get("response_array", [])

        if isinstance(published, str):
            try:
                dt_obj = parser.parse(published)
                formatted_date = dt_obj.strftime("%Y-%m-%d %H:%M")
            except Exception:
                formatted_date = "Unknown date"
        elif isinstance(published, datetime):
            formatted_date = published.strftime("%Y-%m-%d %H:%M")
        else:
            formatted_date = "Unknown date"

        title_to_published[title] = formatted_date

        # Add summary or response_array to candidate line if present
        extras = []
        if summary:
            extras.append(f"Summary: {summary}")
        if response_array:
            extras.append(f"Response Features: {response_array}")

        extra_info = " | ".join(extras)
        if extra_info:
            candidate_lines.append(f"- {title} ({extra_info})")
        else:
            candidate_lines.append(f"- {title}")

    candidate_block = "\n".join(candidate_lines)





# Build detailed rated article block with summaries and response arrays
detailed_rated_block = ""

for article in articles:
    title = article["title"]
    score = score_map.get(article["score"], "unknown")
    rank = article.get("rank_position", "N/A")
    
    # Try to find the matching summary/response_array
    match = next((item for item in summaries if item["title"] == title), None)
    
    if match:
        summary = match.get("summary", "No summary available.")
        response_array = match.get("response_array", [])
    else:
        summary = "No summary available."
        response_array = []

    detailed_rated_block += f'''
Title: "{title}"
- Score: {score}
- Rank: {rank}
- Summary: {summary}
- Response Features: {response_array}
\n'''


#final updated prompt
prompt_text = f"""
{user_name} has rated the following articles.

- Articles rated **strong accept** were highly liked.
- Articles rated **weak accept** were somewhat liked or neutral.
- Articles rated **reject** were disliked.


Rated Articles with Context:
{detailed_rated_block}

Below is a list of new articles available (the candidate pool). Each may include a summary and response_array.

{candidate_block}

## Recommendation Instructions:

You are tasked with recommending 50 article titles from the candidate pool that this user is most likely to enjoy.

1. **Look for patterns in the rated articles**, especially in those marked as **strong accept** and **weak accept**. Pay attention to both the summaries and the `response_array` values across the 11 language lens dimensions.

2. For each candidate article, if a summary is present, use it to understand the content and tone. If a response_array is present, use it to match patterns seen in previously liked articles.

3. Prioritize articles that **match the tone, narrative style, and themes** of liked articles (especially strong accept). 

4. Avoid recommending articles that share **narrative or tonal patterns** with rejected articles.

Return ONLY a bullet-point list of 50 article titles from the candidate pool.
"""



# Claude format
claude_payload = {
    "messages": [
        {"role": "user", "content": prompt_text}
    ],
    "max_tokens": 1024,
    "temperature": 0.7,
    "anthropic_version": "bedrock-2023-05-31"
}

# Call Claude
response = bedrock.invoke_model(
    modelId=model_id,
    contentType="application/json",
    accept="application/json",
    body=json.dumps(claude_payload)
)

# Extract and print response
# Extract and print response
response_body = json.loads(response['body'].read())
recommendations = response_body['content'][0]['text']

print("\nTop 20 Recommended Articles:\n")
for line in recommendations.strip().split("\n"):
    title = line.lstrip("- ").strip()
    pub_date = title_to_published.get(title, "Unknown date")
    print(f"- {title} (Published: {pub_date})")


# Add user summary prompt
summary_prompt = f"""
Based on the following article ratings by {user_name}, describe this user's interests and preferences in 2-3 sentences.

Each article includes:
- A score (strong accept, weak accept, reject)
- A summary
- A response_array: 11 numerical features representing the article's language lens traits

Please consider patterns in both the **response_array** values and the **ratings** to infer the user's language preferences (e.g., whether they prefer factual vs. opinionated, complex vs. simple, etc.).

Rated Articles:
{detailed_rated_block}
"""
traits = [
    "plain_poeticness", "fact_opinion", "critique_affirmation",
    "complexity_simplicity", "general_detailed", "informative_entertaining",
    "upside_downside", "agreement_counterargument", "dry_emotionally_charged",
    "data_narrative", "quoted_authorial"
]

# Create payload for summary
summary_payload = {
    "messages": [
        {"role": "user", "content": summary_prompt}
    ],
    "max_tokens": 256,
    "temperature": 0.5,
    "anthropic_version": "bedrock-2023-05-31"
}

# Call Claude for summary
summary_response = bedrock.invoke_model(
    modelId=model_id,
    contentType="application/json",
    accept="application/json",
    body=json.dumps(summary_payload)
)

# Extract and print summary
summary_body = json.loads(summary_response['body'].read())
user_summary = summary_body['content'][0]['text']

print("\nUser Preference Summary:\n")
print(user_summary)

