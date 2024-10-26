"""news_scraper.py: Contains logic for scraping news articles from an API like NewsAPI.
Calls the news API based on search terms from search_terms.json."""

import os, sys
import requests
from dotenv import load_dotenv
from .database import get_search_terms, insert_raw_article, refresh_search_terms

# Load environment variables
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(project_root)
load_dotenv()
NEWS_API_KEY = os.getenv("NEWS_API_KEY")
NEWS_API_URL = "https://newsapi.org/v2/everything"

def fetch_articles_for_term(search_term):
    """Fetch articles for a given search term using the News API."""
    articles = []
    params = {
        "q": search_term,
        "apiKey": NEWS_API_KEY,
        "pageSize": 100,  # Adjust page size as needed
        "page": 1
    }

    while True:
        response = requests.get(NEWS_API_URL, params=params)
        
        if response.status_code != 200:
            print(f"Error fetching articles for '{search_term}': {response.status_code}")
            break

        data = response.json()
        articles.extend(data.get("articles", []))
        
        # Check if there are more pages
        if len(data.get("articles", [])) < params["pageSize"]:
            break
        else:
            params["page"] += 1  # Move to the next page

    return articles

def scrape_articles():
    """Main function to fetch and store articles for each search term."""
    search_terms = get_search_terms()
    
    for term_id, search_term in search_terms:
        print(f"Scraping articles for search term: {search_term}")
        articles = fetch_articles_for_term(search_term)
        
        for article in articles:
            insert_raw_article(
                search_term_id=term_id,
                title=article["title"],
                content=article.get("content", ""),
                source=article["source"]["name"],
                url=article["url"],
                urlToImage=article.get("urlToImage", ""),
                published_at=article.get("publishedAt")
            )
        print(f"Stored {len(articles)} articles for term '{search_term}'.")

if __name__ == "__main__":
    refresh_search_terms()
    scrape_articles()
