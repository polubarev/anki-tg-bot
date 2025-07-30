# Anki Telegram Bot

This project implements a Telegram bot for creating Anki flashcards. The bot uses OpenAI to generate card content, stores them in a Firestore queue, and pushes them to Anki via AnkiConnect.

## Features

- **Create Anki cards** from a simple Telegram interface.
- **AI-powered content generation** using OpenAI.
- **Queueing system** with Google Firestore to hold cards before pushing them to Anki.
- **One-click push** to a running Anki instance with AnkiConnect.
- **Serverless deployment** on Google Cloud Run.

## Prerequisites

- Python 3.11+
- Google Cloud SDK (`gcloud`)
- Docker
- Anki Desktop with the [AnkiConnect](https://ankiweb.net/shared/info/2055492159) add-on installed.
- A Telegram Bot Token from [@BotFather](https://t.me/BotFather).

## Local Development

1.  **Clone the repository:**
    ```bash
    git clone <repository-url>
    cd anki_bot
    ```

2.  **Create a virtual environment and install dependencies:**
    ```bash
    python -m venv .venv
    source .venv/bin/activate  # On Windows, use `.venv\Scripts\activate`
    pip install -r requirements.txt
    ```

3.  **Set up authentication:**
    - **Google Cloud:**
      ```bash
      gcloud auth application-default login
      ```
    - **Secrets:** Create a `.env` file and add the following:
      ```
      GOOGLE_CLOUD_PROJECT="your-gcp-project-id"
      TG_TOKEN="your-telegram-bot-token"
      OPENAI_KEY="your-openai-api-key"
      ANKI_URL="your-ankiconnect-url"
      ```
      *Note: For local testing, you might need to expose your local AnkiConnect to the web using a tool like ngrok.*

4.  **Run the bot locally:**
    ```bash
    python bot.py
    ```

## Cloud Deployment (Google Cloud Run)

1.  **Enable necessary Google Cloud APIs:**
    ```bash
    gcloud services enable run.googleapis.com firestore.googleapis.com secretmanager.googleapis.com
    ```

2.  **Create a Firestore database.**

3.  **Store secrets in Secret Manager:**
    ```bash
    gcloud secrets create tg-token --data-file=- <<< "your-telegram-bot-token"
    gcloud secrets create openai-key --data-file=- <<< "your-openai-api-key"
    gcloud secrets create anki-url --data-file=- <<< "your-ankiconnect-url"
    ```

4.  **Build and deploy the Docker image to Cloud Run:**
    ```bash
    gcloud builds submit --tag gcr.io/$(gcloud config get-value project)/anki-bot
    gcloud run deploy anki-bot \
      --image gcr.io/$(gcloud config get-value project)/anki-bot \
      --platform managed \
      --region us-central1 \
      --allow-unauthenticated \
      --set-secrets="TG_TOKEN=tg-token:latest,OPENAI_KEY=openai-key:latest,ANKI_URL=anki-url:latest"
    ```

5.  **Set the Telegram webhook** to the URL provided by Cloud Run.

## Usage

-   **/start**: Initialize the bot and see the main menu.
-   **➕ Add Card**: Prompts the bot to listen for the next message to be turned into a card.
-   **🚀 Push**: Pushes all cards from the Firestore queue to Anki.
-   **📋 List**: Shows the current cards in the queue.
-   **🗑 Clear**: Deletes all cards from the queue.

## Docker

You can build and run the bot using Docker:

```bash
# Build the image
docker build -t anki-bot .

# Run the container
docker run -d --env-file .env anki-bot
```

## Contributing

Contributions are welcome! Please open an issue to discuss any major changes before submitting a pull request.

