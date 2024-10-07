# Vision News Analyzer

## Overview
**Vision News Analyzer** is an AI-powered tool that scrapes news articles based on predefined search terms, filters them for relevance using natural language processing, and processes associated images with object detection (powered by YOLO). This system is designed to deliver targeted insights by analyzing both text and visual data from news sources.

## Features
- **News Scraping**: Automatically scrape news articles from various sources using search terms.
- **Relevance Filtering**: Use AI models to filter and rank articles based on relevance to a specified topic.
- **Image Processing**: Perform object detection on images related to the articles, using the YOLO model.
- **Customizable Search Terms**: Dynamically update search terms and topics of interest.
- **REST API**: Expose a simple API to search and retrieve relevant articles and object detection results.

## Getting Started

### Prerequisites
Before you can run this project, you’ll need to have the following installed:
- **Python 3.8+**
- **YOLO (You Only Look Once)**: For object detection in images.
- **OpenAI API key**: For relevance filtering.
- **News API key**: To fetch news articles (e.g., [NewsAPI](https://newsapi.org/)).
- **Docker** (optional): For containerized deployment.

### Installation

1. **Clone the repository**:
   ```bash
   git clone https://github.com/yourusername/vision-news-analyzer.git
   cd vision-news-analyzer
   ```

2. **Set up a virtual environment** (recommended):
   ```bash
   python3 -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Set up YOLO for object detection**:
   - Download the pre-trained YOLO model weights (e.g., YOLOv5) and place them in the `models/yolo` directory.
   - Follow the YOLO documentation for setting up and testing the model.

5. **Set up environment variables**:
   Create a `.env` file in the root directory with your API keys and configurations:
   ```bash
   NEWS_API_KEY=your_news_api_key
   OPENAI_API_KEY=your_openai_api_key
   YOLO_MODEL_PATH=path/to/your/yolo/weights
   ```

### Usage

1. **Running the Application**:
   - You can start the application by running the Python script:
     ```bash
     python app.py
     ```

2. **Scraping and Filtering News**:
   - The system automatically scrapes articles using predefined search terms, scores their relevance using the OpenAI API, and stores relevant articles.
   - You can update the search terms by editing the configuration in `config/search_terms.json`.

3. **Object Detection in Images**:
   - YOLO is used to detect specific objects in images associated with the articles. Detected objects are tagged and stored in the database.

4. **API Endpoints**:
   - The application exposes a REST API for retrieving articles and object detection results. You can query the data via the following endpoints:
     - `GET /api/articles`: Retrieve relevant articles.
     - `GET /api/articles/{id}/images`: Retrieve images and detected objects for a specific article.

### Example Workflow
1. Add a list of search terms in `config/search_terms.json`.
2. Run the script to scrape and analyze news articles.
3. Use the REST API to query for relevant articles and associated images.
4. The system will return both text-based relevance and object detection results for each article.

### Configuration

- **Search Terms**: Configure the search terms for scraping in `config/search_terms.json`.
- **YOLO Model**: Specify the YOLO model weights path in your `.env` file (`YOLO_MODEL_PATH`).
- **Relevance Threshold**: Adjust the relevance score threshold in `config/relevance_threshold.json`.

### Deployment

For production, you can containerize the application using **Docker**:
1. Build the Docker image:
   ```bash
   docker build -t vision-news-analyzer .
   ```
2. Run the container:
   ```bash
   docker run -d -p 5000:5000 --env-file .env vision-news-analyzer
   ```

### Contributing

Feel free to submit issues and pull requests if you'd like to contribute to the project.

### License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
