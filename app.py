from flask import Flask, request, jsonify

app = Flask(__name__)

@app.route('/', methods=['POST'])
def main():
    event = request.get_json()
    command = event.get('request', {}).get('command', '').lower()

    if 'привет' in command:
        text = 'Привет! Это навык ПРАКТИКУМ. Чем могу помочь?'
    else:
        text = 'Я пока не понял тебя, попробуй сказать "помощь".'

    return jsonify({
        "version": "1.0",
        "session": event.get("session", {}),
        "response": {
            "text": text,
            "end_session": False
        }
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
