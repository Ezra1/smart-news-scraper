import os
import requests
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
NEWS_API_KEY = os.getenv("NEWS_API_KEY")
NEWS_API_URL = "https://newsapi.org/v2/everything"

def test_news_api():
    """Test function to check if the News API is working."""
    search_term = "sample news"  # Example search term
    params = {
        "q": search_term,
        "apiKey": NEWS_API_KEY,
        "pageSize": 5,  # Limit the number of articles to retrieve
    }

    response = requests.get(NEWS_API_URL, params=params)
    
    # Check if the API call was successful
    if response.status_code == 200:
        data = response.json()
        articles = data.get("articles", [])
        print(f"API is working. Retrieved {len(articles)} articles for term '{search_term}':")
        for i, article in enumerate(articles, start=1):
            print(f"{i}. {article['title']} - {article['source']['name']}")
    else:
        print(f"Failed to connect to the News API. Status Code: {response.status_code}")
        print("Error Message:", response.json().get("message"))

if __name__ == "__main__":
    test_news_api()
