from openai import OpenAI
import os
from dotenv import load_dotenv
load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OpenAI.api_key = OPENAI_API_KEY

client = OpenAI()
"""
"For checking if the OpenAI call works"
completion = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[
        {"role": "system", "content": "You are a helpful assistant."},
        {
            "role": "user",
            "content": "Write a haiku about recursion in programming."
        }
    ]
)

print(completion.choices[0].message)
"""

def list_running_batches():
    try:
        # Retrieve all batches with a limit on the number of results
        all_batches = client.batches.list(limit=100)
        
        # Filter batches to only include those that are "in_progress" or "validating"
        running_batches = [
            batch for batch in all_batches.data 
            if batch.status in ["in_progress", "validating"]
        ]
        
        # Display the running batches
        for batch in running_batches:
            print(f"Batch ID: {batch.id}, Status: {batch.status}, Created At: {batch.created_at}")
        
        if not running_batches:
            print("No batches are currently running.")
    
    except Exception as e:
        print(f"Error fetching running batches: {e}")

# Call the function to check running batches
list_running_batches()
