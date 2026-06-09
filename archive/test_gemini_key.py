import os
from langchain_google_genai import ChatGoogleGenerativeAI
from dotenv import load_dotenv

def test_gemini_pro():
    print("Testing Gemini API Key...")
    
    # Load .env file
    load_dotenv()
    
    # Get the API key
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    
    if not api_key:
        print("[ERROR] GEMINI_API_KEY or GOOGLE_API_KEY not found in environment variables.")
        print("Please add your key to the .env file like this:\nGEMINI_API_KEY=your_api_key_here")
        return

    # To ensure langchain uses our exact key even if GOOGLE_API_KEY isn't set
    if not os.environ.get("GOOGLE_API_KEY") and api_key:
        os.environ["GOOGLE_API_KEY"] = api_key

    try:
        # Initialize the model specifically requesting gemini-2.0-flash
        model_name = "gemini-2.0-flash"
        print(f"Connecting to model: {model_name}...")
        
        llm = ChatGoogleGenerativeAI(
            model=model_name,
            temperature=0.0
        )
        
        # Send a simple test prompt
        response = llm.invoke("Reply with the exact word 'SUCCESS' if you receive this message.")
        
        if "SUCCESS" in response.content.upper():
            print(f"\n[SUCCESS] Your API key is valid and you have access to the {model_name} model.")
            print(f"Response: {response.content.strip()}")
        else:
            print(f"\n[WARNING] The request succeeded, but got an unexpected response: {response.content}")
            
    except Exception as e:
        print("\n[FAILURE] Could not access the model.")
        print(f"Error Details: {str(e)}")
        print("\nPossible reasons:")
        print("1. Your API key is invalid.")
        print("2. You do not have access/quota for 'gemini-2.5-pro'.")
        print("3. Network/connection issue to Google servers.")

if __name__ == "__main__":
    test_gemini_pro()
