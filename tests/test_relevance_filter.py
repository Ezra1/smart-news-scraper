"""tests/test_relevance_filter.py"""

import os
import json
import time
from pathlib import Path
from openai import OpenAI
from dotenv import load_dotenv

def test_batch_processing():
    load_dotenv()
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    
    test_data = [
        {
            "custom_id": "test-1",
            "method": "POST",
            "url": "/v1/chat/completions",
            "body": {
                "model": "gpt-4",
                "messages": [
                    {"role": "user", "content": "What is 2+2?"}
                ]
            }
        },
        {
            "custom_id": "test-2",
            "method": "POST",
            "url": "/v1/chat/completions",
            "body": {
                "model": "gpt-4",
                "messages": [
                    {"role": "user", "content": "What is 3+3?"}
                ]
            }
        }
    ]
    
    input_path = Path("test_batch_input.jsonl")
    with open(input_path, "w") as f:
        for item in test_data:
            f.write(json.dumps(item) + "\n")
    
    try:
        print("Uploading file...")
        with open(input_path, "rb") as f:
            file = client.files.create(file=f, purpose="batch")
        
        print("Creating batch job...")
        batch = client.batches.create(
            input_file_id=file.id,
            endpoint="/v1/chat/completions",
            completion_window="24h"  # Added missing required parameter
        )
        
        print(f"Checking batch status (ID: {batch.id})...")
        while True:
            status = client.batches.retrieve(batch.id)
            print(f"Status: {status.status}")
            
            if status.status == "completed":
                output = client.files.content(status.output_file_id)
                with open("test_batch_output.jsonl", "w") as f:
                    f.write(output.text)
                print("Results saved to test_batch_output.jsonl")
                break
            
            if status.status in ["failed", "expired"]:
                raise Exception(f"Batch failed with status: {status.status}")
                
            time.sleep(30)
            
    except Exception as e:
        print(f"Error: {str(e)}")
    finally:
        input_path.unlink(missing_ok=True)

if __name__ == "__main__":
    test_batch_processing()