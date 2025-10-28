from flask import Flask, request, jsonify
import openpyxl
import random
import re
import os

app = Flask(__name__)

# 📂 Путь к Excel-файлу
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
excel_path = os.path.join(BASE_DIR, "questions.xlsx")

if not os.path.exists(excel_path):
    raise FileNotFoundError(f"Файл {excel_path} не найден!")

# Загружаем Excel
workbook = openpyxl.load_workbook(excel_path)
sheet_names = workbook.sheetnames

# ===============================
# 🔹 Подготовка базы вопросов
# ===============================
def parse_options(options_str):
    return [opt.strip() for opt in str(options_str).split(';') if opt.strip()]

def parse_correct(correct_str):
    correct_list = []
    for item in str(correct_str).split(";"):
        match = re.match(r"([А-ЯЁA-Z]\))", item.strip())
        if match:
            correct_list.append(match.group(1))
    return correct_list

quizzes = {}
for sheet_name in sheet_names:
    sheet = workbook[sheet_name]
    data = []
    for row in sheet.iter_rows(min_row=2, values_only=True):
        if all(cell is None for cell in row):
            continue
        question, options, correct, explanation = (row + (None, None, None, None))[:4]
        data.append({
            "Вопрос": str(question).strip(),
            "Варианты": parse_options(options),
            "Правильный": parse_correct(correct),
            "Пояснение": str(explanation).strip() if explanation else ""
        })
    quizzes[sheet_name] = data

def get_random_question(topic):
    return random.choice(quizzes[topic])

# ===============================
# 🚀 Основной Webhook
# ===============================
@app.route("/", methods=["POST"])
def main():
    req = request.json
    command = req["request"]["command"].strip().lower()
    session = req.get("session", {})
    state = req.get("state", {}).get("session", {})

    response = {
        "version": req["version"],
        "session": req["session"],
        "response": {"end_session": False, "text": "", "buttons": []}
    }

    # 1️⃣ Новая сессия — приветствие
    if session.get("new", False):
        buttons = [{"title": f"{i+1}. {name}"} for i, name in enumerate(sheet_names)]
        response["response"]["text"] = "Привет! 👋 Выберите блок по кнопке ниже:"
        response["response"]["buttons"] = buttons
        return jsonify(response)

    # 2️⃣ Назад в меню
    if command in ["назад", "в меню", "назад в меню"]:
        response["response"]["text"] = "Вы вернулись в меню. Выберите блок:"
        response["response"]["buttons"] = [{"title": f"{i+1}. {name}"} for i, name in enumerate(sheet_names)]
        response["session_state"] = {}
        return jsonify(response)

    # 3️⃣ Проверка выбора блока (только по кнопке)
    for i, sheet_name in enumerate(sheet_names):
        if command == f"{i+1}. {sheet_name}".lower():
            topic = sheet_name
            question = get_random_question(topic)
            response["response"]["text"] = (
                f'Вы выбрали "{topic}".\n\n'
                f'{question["Вопрос"]}\n'
                f'Варианты:\n' + "\n".join([f"{opt}" for opt in question["Варианты"]])
            )
            response["response"]["buttons"] = [{"title": "Назад в меню"}]
            response["session_state"] = {"topic": topic, "question": question}
            return jsonify(response)

    # 4️⃣ Ответ на вопрос
    if "question" in state and "topic" in state:
        topic = state["topic"]
        question = state["question"]
        correct = [c.lower().replace(")", "").strip() for c in question["Правильный"]]

        user_answer = command.replace(")", "").replace(".", "").strip()

        # поддержка цифр 1/2/3 → А/Б/В
        letter_map = {"1": "а", "2": "б", "3": "в"}
        if user_answer in letter_map:
            user_answer = letter_map[user_answer]

        # проверяем правильность
        if user_answer in correct:
            text = f"✅ Верно!\n\n{question['Пояснение']}"
        else:
            text = f"❌ Неверно.\n\n{question['Пояснение']}"

        # следующий вопрос
        next_q = get_random_question(topic)
        text += (
            f"\n\nСледующий вопрос:\n{next_q['Вопрос']}\n" +
            "\n".join(next_q["Варианты"])
        )

        response["response"]["text"] = text
        response["response"]["buttons"] = [{"title": "Назад в меню"}]
        response["session_state"] = {"topic": topic, "question": next_q}
        return jsonify(response)

    # 5️⃣ Если пользователь пишет что-то, не нажимая кнопку
    response["response"]["text"] = "Пожалуйста, выберите блок по кнопке ниже 👇"
    response["response"]["buttons"] = [{"title": f"{i+1}. {name}"} for i, name in enumerate(sheet_names)]
    return jsonify(response)

# Проверка на GET
@app.route("/", methods=["GET"])
def home():
    return "Навык Алисы работает!", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
