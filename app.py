from flask import Flask, request, jsonify
import openpyxl
import random
import re
import os

app = Flask(__name__)

# 📂 Путь к Excel-файлу (он должен лежать в одной папке с app.py)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
excel_path = os.path.join(BASE_DIR, "questions.xlsx")

if not os.path.exists(excel_path):
    raise FileNotFoundError(f"Файл {excel_path} не найден!")

# Загружаем Excel
workbook = openpyxl.load_workbook(excel_path)
sheet_names = workbook.sheetnames

quizzes = {}

# 🔹 Функции для обработки текста
def parse_options(options_str):
    return [opt.strip() for opt in str(options_str).split(';') if opt.strip()]

def parse_correct(correct_str):
    correct_list = []
    for item in str(correct_str).split(";"):
        match = re.match(r"([А-ЯЁ]\))", item.strip())
        if match:
            correct_list.append(match.group(1))
    return correct_list

# 🔹 Загружаем вопросы из каждого листа
for sheet_name in sheet_names:
    sheet = workbook[sheet_name]
    data = []
    for row in sheet.iter_rows(min_row=2, values_only=True):
        if all(cell is None for cell in row):
            continue
        row_data = tuple((str(cell).strip() if cell is not None else "") for cell in (row + (None, None, None, None))[:4])
        question, options, correct, explanation = row_data
        data.append({
            "Вопрос": question,
            "Варианты": parse_options(options),
            "Правильный": parse_correct(correct),
            "Пояснение": explanation
        })
    quizzes[sheet_name] = data

def get_random_question(topic):
    return random.choice(quizzes[topic])

# ===============================
# 🚀 ОСНОВНОЙ ВЕБХУК ДЛЯ АЛИСЫ
# ===============================
@app.route("/", methods=["POST"])
def main():
    req = request.json
    session = req.get("session", {})
    state = req.get("state", {}).get("session", {})
    command = req["request"]["command"].strip()

    response = {
        "version": req["version"],
        "session": req["session"],
        "response": {"end_session": False}
    }

    # Создаём сопоставление цифра -> лист Excel
    number_to_sheet = {str(i+1): name for i, name in enumerate(sheet_names)}

    # Новая сессия — показываем блоки
    if session.get("new", False):
        buttons = [{"title": f"{i+1}. {name}"} for i, name in enumerate(sheet_names)]
        response["response"]["text"] = "Привет! Выберите блок по номеру или названию:"
        response["response"]["buttons"] = buttons
        return jsonify(response)

    # Определяем выбранный блок по номеру или названию
    selected_topic = None
    for i, name in enumerate(sheet_names):
        if command == str(i+1) or command.lower() == name.lower():
            selected_topic = name
            break

    # Пользователь выбрал блок
    if selected_topic:
        question = get_random_question(selected_topic)
        response["response"]["text"] = (
            f'Вы выбрали "{selected_topic}". Начнём тренировку.\n{question["Вопрос"]}\n'
            f'Варианты:\n' + "\n".join([f"{i+1}. {opt}" for i, opt in enumerate(question["Варианты"])])
        )
        response["session_state"] = {"topic": selected_topic, "question": question}
        return jsonify(response)

    # Пользователь отвечает на вопрос
    if state.get("question"):
        topic = state["topic"]
        question = state["question"]
        correct = question["Правильный"]

        # Разбираем ответ пользователя
        user_answers = re.findall(r'[А-ЯЁ]\)', command.upper())
        if not user_answers:
            # Если пользователь вводит цифру
            mapping = {str(i+1): opt for i, opt in enumerate(question["Варианты"])}
            user_answers = [mapping.get(command.strip())] if mapping.get(command.strip()) else []

        if sorted(user_answers) == sorted(correct):
            next_q = get_random_question(topic)
            response["response"]["text"] = (
                f"Верно! 🎉 Следующий вопрос:\n{next_q['Вопрос']}\n"
                f'Варианты:\n' + "\n".join([f"{i+1}. {opt}" for i, opt in enumerate(next_q["Варианты"])])
            )
            response["session_state"] = {"topic": topic, "question": next_q}
        else:
            response["response"]["text"] = (
                f"Неверно 😢\nПравильный ответ: {', '.join(correct)}\n{question['Пояснение']}\n"
                "Выберите блок заново."
            )
            response["response"]["buttons"] = [{"title": f"{i+1}. {name}"} for i, name in enumerate(sheet_names)]
            response["session_state"] = {}

        return jsonify(response)

    # Если команда непонятна
    response["response"]["text"] = "Пожалуйста, выберите блок по номеру или названию."
    response["response"]["buttons"] = [{"title": f"{i+1}. {name}"} for i, name in enumerate(sheet_names)]
    return jsonify(response)

# ===============================
# 🌐 ПРОВЕРОЧНЫЙ МАРШРУТ
# ===============================
@app.route("/", methods=["GET"])
def home():
    return "Навык Алисы работает!", 200


# ===============================
# 🔥 ЗАПУСК
# ===============================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
