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
    if not options_str:
        return []
    return [opt.strip() for opt in str(options_str).split(';') if opt.strip()]


def parse_correct(correct_str):
    if not correct_str:
        return []
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
        if not question:
            continue
        data.append({
            "Вопрос": str(question).strip(),
            "Варианты": parse_options(options),
            "Правильный": parse_correct(correct),
            "Пояснение": str(explanation).strip() if explanation else ""
        })
    quizzes[sheet_name] = data


def get_random_question(topic):
    if topic not in quizzes or not quizzes[topic]:
        return None
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
        buttons = [{"title": name} for name in sheet_names]
        response["response"]["text"] = "Привет! 👋 Выберите тему для тестирования:"
        response["response"]["buttons"] = buttons
        return jsonify(response)

    # 2️⃣ Назад в меню
    if command in ["назад", "в меню", "меню", "главная"]:
        buttons = [{"title": name} for name in sheet_names]
        response["response"]["text"] = "Вы вернулись в главное меню. Выберите тему:"
        response["response"]["buttons"] = buttons
        response["session_state"] = {}
        return jsonify(response)

    # 3️⃣ Проверка выбора темы
    for sheet_name in sheet_names:
        if command == sheet_name.lower():
            topic = sheet_name
            question = get_random_question(topic)
            if not question:
                response["response"]["text"] = f"В теме '{topic}' нет вопросов."
                response["response"]["buttons"] = [{"title": "Назад в меню"}]
                return jsonify(response)

            options_text = "\n".join([f"{opt}" for opt in question["Варианты"]]) if question["Варианты"] else ""
            response["response"]["text"] = (
                f'Тема: "{topic}"\n\n'
                f'{question["Вопрос"]}\n\n'
                f'{options_text}'
            )
            response["response"]["buttons"] = [{"title": "Назад в меню"}]
            response["session_state"] = {"topic": topic, "question": question}
            return jsonify(response)

    # 4️⃣ Ответ на вопрос
    if state.get("topic") and state.get("question"):
        topic = state["topic"]
        question = state["question"]
        correct_answers = [c.lower().replace(")", "").strip() for c in question["Правильный"]]

        user_answer = command.replace(")", "").replace(".", "").strip().lower()

        # поддержка цифр 1/2/3 → а/б/в
        letter_map = {"1": "а", "2": "б", "3": "в", "4": "г", "5": "д"}
        if user_answer in letter_map:
            user_answer = letter_map[user_answer]

        # проверяем правильность
        if user_answer in correct_answers:
            text = f"✅ Верно!\n\n{question['Пояснение']}"
        else:
            correct_text = ", ".join(question["Правильный"])
            text = f"❌ Неверно.\n\nПравильный ответ: {correct_text}\n\n{question['Пояснение']}"

        # следующий вопрос
        next_question = get_random_question(topic)
        if next_question:
            options_text = "\n".join([f"{opt}" for opt in next_question["Варианты"]]) if next_question[
                "Варианты"] else ""
            text += (
                f"\n\nСледующий вопрос:\n{next_question['Вопрос']}\n\n"
                f"{options_text}"
            )
            response["session_state"] = {"topic": topic, "question": next_question}
        else:
            text += "\n\nВопросы в этой теме закончились!"
            response["session_state"] = {}

        response["response"]["text"] = text
        response["response"]["buttons"] = [{"title": "Назад в меню"}]
        return jsonify(response)

    # 5️⃣ Если команда не распознана
    buttons = [{"title": name} for name in sheet_names]
    response["response"]["text"] = "Пожалуйста, выберите тему из предложенных ниже 👇"
    response["response"]["buttons"] = buttons
    return jsonify(response)


# Проверка на GET
@app.route("/", methods=["GET"])
def home():
    return "Навык Алисы работает!", 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)