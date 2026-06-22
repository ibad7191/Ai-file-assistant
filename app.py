from flask import Flask, request, jsonify, render_template
from google import genai
import os
import uuid
import time
from datetime import datetime

app = Flask(__name__, static_folder="static", template_folder="templates")

# 🔑 APNI API KEY YAHAN PASTE KARO
API_KEY = "PUT_YOUR_API_KEY"

# ✅ FIX 1: API version specify karo (v1beta)
client = genai.Client(
    api_key=API_KEY,
    http_options={"api_version": "v1beta"}  # <-- Yeh important hai!
)

# Store chat history in memory
CONVERSATIONS = {}

# Retry function for handling quota issues
def call_gemini_with_retry(model, contents, max_retries=3):
    """
    Gemini API call with automatic retry on quota exhaustion
    """
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model=model,
                contents=contents
            )
            return response
        except Exception as e:
            error_msg = str(e)
            
            # If quota exhausted, wait and retry
            if "RESOURCE_EXHAUSTED" in error_msg or "429" in error_msg:
                wait_time = (attempt + 1) * 10  # 10, 20, 30 seconds
                print(f"⚠️ Quota exceeded. Waiting {wait_time} seconds... (Attempt {attempt+1}/{max_retries})")
                time.sleep(wait_time)
                
                if attempt == max_retries - 1:
                    raise Exception("Quota exhausted. Please try after some time.")
            else:
                raise e

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/upload", methods=["POST"])
def upload():
    """
    Handles file uploads: image, PDF, or audio.
    """
    temp_path = None
    try:
        if "file" not in request.files:
            return jsonify({"error": "No file uploaded"}), 400

        file = request.files["file"]
        task = request.form.get("task", "general")

        # Check if file is empty
        if file.filename == '':
            return jsonify({"error": "No file selected"}), 400

        # Save temporarily with unique name
        temp_path = os.path.join("temp_" + str(uuid.uuid4()) + "_" + file.filename)
        file.save(temp_path)

        # Upload to Gemini
        uploaded_file = client.files.upload(file=temp_path)

        # Pick prompt based on task
        if task == "pdf":
            prompt = "Summarize this PDF in key points using bullet points (•). Keep each point short and clear."
        elif task == "audio":
            prompt = "Transcribe this audio file and present the content in key points using bullet points (•). Include main topics discussed."
        elif task == "image":
            prompt = "Describe this image in key points using bullet points (•). Include objects, colors, setting, and important details."
        else:
            prompt = "Analyze this file and provide key information in bullet points (•). Keep points short and clear."

        # ✅ FIX 2: Model change karo (gemini-1.5-flash use karo)
        response = call_gemini_with_retry(
            model="gemini-2.5-flash",  # <-- Ye model ab chalega
            contents=[uploaded_file, prompt]
        )

        # Clean up temp file
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)
        
        return jsonify({
            "extracted_text": response.text,
            "success": True
        })

    except Exception as e:
        # Clean up temp file if it exists
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except:
                pass
        return jsonify({"error": str(e), "success": False}), 500

@app.route("/chat", methods=["POST"])
def chat():
    """
    Handles chat messages with optional context.
    """
    try:
        data = request.json or {}
        message = data.get("message", "").strip()
        session_id = data.get("session_id") or str(uuid.uuid4())
        context_text = data.get("context_text", "")

        # Validate message
        if not message:
            return jsonify({"error": "Message cannot be empty"}), 400

        # Initialize conversation if new session
        if session_id not in CONVERSATIONS:
            CONVERSATIONS[session_id] = []

        # Build conversation content
        conversation_parts = []
        
        # System instruction
        system_instruction = """You are Chatboard, an AI assistant. ALWAYS respond in key points format using bullet points (•). 
Keep each point short, clear and actionable. Never write long paragraphs - only bullet points."""
        conversation_parts.append(f"System: {system_instruction}")
        
        # Add previous conversation history (last 10 messages only to save tokens)
        history_limit = 10
        recent_history = CONVERSATIONS[session_id][-history_limit:] if CONVERSATIONS[session_id] else []
        
        for msg in recent_history:
            if msg["role"] == "user":
                conversation_parts.append(f"User: {msg['content']}")
            elif msg["role"] == "assistant":
                conversation_parts.append(f"Assistant: {msg['content']}")

        # Add context from file if available
        if context_text:
            conversation_parts.append(f"Context from uploaded file: {context_text[:1000]}")  # Limit context length

        # Add current user message
        conversation_parts.append(f"User: {message}")
        conversation_parts.append("Please respond in key points format using bullet points (•).")
        
        # Store user message in history
        CONVERSATIONS[session_id].append({"role": "user", "content": message})

        # Join all parts
        full_prompt = "\n\n".join(conversation_parts)

        # ✅ FIX 2: Model change karo (gemini-1.5-flash use karo)
        response = call_gemini_with_retry(
            model="gemini-2.5-flash",  # <-- Ye model ab chalega
            contents=full_prompt
        )

        reply = response.text.strip()
        
        # Store assistant reply in conversation history
        CONVERSATIONS[session_id].append({"role": "assistant", "content": reply})

        return jsonify({
            "session_id": session_id, 
            "reply": reply,
            "success": True
        })

    except Exception as e:
        return jsonify({"error": str(e), "success": False}), 500

@app.route("/history/<session_id>", methods=["GET"])
def history(session_id):
    """
    Get chat history for a session.
    """
    messages = CONVERSATIONS.get(session_id, [])
    return jsonify({
        "session_id": session_id,
        "messages": messages,
        "count": len(messages),
        "success": True
    })

@app.route("/clear/<session_id>", methods=["POST"])
def clear_history(session_id):
    """
    Clear chat history for a session.
    """
    if session_id in CONVERSATIONS:
        CONVERSATIONS[session_id] = []
        return jsonify({"success": True, "message": "History cleared"})
    return jsonify({"success": False, "message": "Session not found"}), 404

@app.route("/health", methods=["GET"])
def health():
    """
    Health check endpoint.
    """
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "active_sessions": len(CONVERSATIONS)
    })

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)