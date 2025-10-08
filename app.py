
from flask import Flask, request, jsonify, render_template
import asyncio

from web_handlers import process_web_request

app = Flask(__name__)

@app.route("/")
def index():
    return render_template("chat.html")

@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.json
    user_id = data.get("user_id", "web_user")
    message = data.get("message")

    if not message:
        return jsonify({"error": "Message is required"}), 400

    # Since the handler is async, we need to run it in an event loop
    response = asyncio.run(process_web_request(user_id, message))
    
    return jsonify({"response": response})

if __name__ == "__main__":
    app.run(debug=True)
