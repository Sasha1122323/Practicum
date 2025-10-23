from flask import Flask, request, jsonify
import openpyxl
import random
import re

app = Flask(__name__)

# Загружаем Excel-файл
workbook = openpyxl.load_workbook("questions.xlsx")
sheet_names = workbook.sheetnames

quizzes = {}

# Функция для парсинга вариантов
def parse_options(options_str):
    # Варианты разделены ';'
    options = [opt.strip() for opt in options_str.split(';') if opt.strip()]
    return options

# Функция для парсинга правильных ответов
def parse_correct(correct_str):
    # Правильные варианты могут быть через ';' или пробел
    # Берём только букву с )
    return [opt.strip() for opt in re.split(r'[; ]+', correct_str) if opt.strip()]

# Загружаем вопросы по листам
for sheet_name in sheet_names:
    sheet = workbook[sheet_name]
    data = []
    for row in sheet.iter_rows(min_row=2, values_only=True):
        if not row or not row[0]:
            continue
        # Берём только первые 4 значения, если их больше, или дополняем None, если меньше
        question, options, correct, explanation = (row + (None, None, None, None))[:4]

        data.append({
            "Вопрос": str(question).strip() if question else "",
            "Варианты": parse_options(str(options)) if options else [],
            "Правильный": parse_correct(str(correct)) if correct else [],
            "Пояснение": str(explanation).strip() if explanation else ""
        })
    quizzes[sheet_name] = data


def get_random_question(sheet_name):
    return random.choice(quizzes[sheet_name])

@app.route("/", methods=["POST"])
def main():
    req = request.json
    session = req.get("session", {})
    state = req.get("state", {}).get("session", {})
    command = req["request"]["command"].strip().upper()

    response = {
        "version": req["version"],
        "session": req["session"],
        "response": {"end_session": False}
    }

    # Приветствие
    if session.get("new", False):
        response["response"]["text"] = "Привет! Выбери документ (лист) для викторины:"
        response["response"]["buttons"] = [{"title": name} for name in sheet_names]
        return jsonify(response)

    # Пользователь выбрал лист
    if command.capitalize() in sheet_names:
        topic = command.capitalize()
        question = get_random_question(topic)
        response["response"]["text"] = (
            f'Вы выбрали "{topic}".\n{question["Вопрос"]}\n'
            f'Варианты: {", ".join(question["Варианты"])}'
        )
        response["session_state"] = {"topic": topic, "question": question}
        return jsonify(response)

    # Пользователь отвечает на вопрос
    if state.get("question"):
        topic = state["topic"]
        question = state["question"]
        correct = question["Правильный"]

        # Разделяем ответ пользователя на варианты
        user_answers = re.findall(r'[А-ЯЁ]\)', command)

        if sorted(user_answers) == sorted(correct):
            next_q = get_random_question(topic)
            response["response"]["text"] = (
                f"Правильно! 🎉\nСледующий вопрос:\n{next_q['Вопрос']}\n"
                f"Варианты: {', '.join(next_q['Варианты'])}"
            )
            response["session_state"] = {"topic": topic, "question": next_q}
        else:
            response["response"]["text"] = (
                f"Неправильно 😢\n{question['Пояснение']}\nВыбери документ заново."
            )
            response["response"]["buttons"] = [{"title": name} for name in sheet_names]
            response["session_state"] = {}
        return jsonify(response)

    # Если команда непонятна
    response["response"]["text"] = "Я не поняла. Выбери документ:"
    response["response"]["buttons"] = [{"title": name} for name in sheet_names]
    return jsonify(response)

@app.route("/", methods=["GET"])
def ping():
    return "Навык Алисы работает!", 200


