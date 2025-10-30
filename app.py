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
    # Ищем все варианты типа "А)", "Б)", "В)" в тексте
    matches = re.findall(r'([А-ЯЁA-Z]\))', str(correct_str))
    return matches


def parse_multiple_answers(command):
    """Парсит несколько ответов из одной команды"""
    # Удаляем лишние символы и разбиваем по пробелам/запятым
    cleaned = re.sub(r'[.,;]', ' ', command.lower())
    answers = cleaned.split()

    # Нормализуем каждый ответ
    normalized_answers = []
    for answer in answers:
        normalized = normalize_answer(answer)
        if normalized and normalized in 'абвгдежзийклмнопрстуфхцчшщъыьэюя':
            normalized_answers.append(normalized)

    return normalized_answers

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


def get_random_question(topic, previous_questions=None):
    """Получает случайный вопрос, исключая предыдущие"""
    if topic not in quizzes or not quizzes[topic]:
        return None

    if previous_questions is None:
        previous_questions = []

    # Фильтруем вопросы, которые уже были
    available_questions = [q for q in quizzes[topic] if q["Вопрос"] not in previous_questions]

    # Если все вопросы использованы, начинаем заново
    if not available_questions:
        available_questions = quizzes[topic]

    return random.choice(available_questions)


def normalize_answer(user_answer):
    """Нормализует ответ пользователя к формату буквы без скобок"""
    if not user_answer:
        return ""

    user_answer = user_answer.strip().lower()

    # Преобразование цифр в буквы
    digit_to_letter = {"1": "а", "2": "б", "3": "в", "4": "г", "5": "д", "6": "е"}
    if user_answer in digit_to_letter:
        return digit_to_letter[user_answer]

    # Удаление скобок, точек и пробелов, оставляем только первую букву
    user_answer = re.sub(r'[).\s]', '', user_answer)
    return user_answer[0] if user_answer else ""


def normalize_correct_answers(correct_answers):
    """Нормализует правильные ответы к формату букв без скобок"""
    normalized = []
    for answer in correct_answers:
        # Удаляем скобки и пробелы, переводим в нижний регистр
        clean_answer = re.sub(r'[)\s]', '', answer).lower()
        if clean_answer:
            normalized.append(clean_answer[0])  # Берем только первую букву
    return normalized


# ===============================
# 🚀 Основной Webhook
# ===============================
@app.route("/", methods=["POST"])
def main():
    req = request.json
    command = req["request"]["command"].strip().lower()
    session = req.get("session", {})

    # ВАЖНО: используем user_state вместо session_state
    state = req.get("state", {}).get("user", {})

    response = {
        "version": req["version"],
        "session": req["session"],
        "response": {"end_session": False, "text": "", "buttons": []},
        "user_state_update": {}  # Добавляем это для сохранения состояния
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
        response["user_state_update"] = {}  # Очищаем состояние
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
            # Сохраняем в user_state_update
            response["user_state_update"] = {
                "topic": topic,
                "question": question,
                "previous_questions": [question["Вопрос"]]  # Сохраняем историю вопросов
            }
            return jsonify(response)

    # 4️⃣ Проверка на неизвестные команды в режиме вопроса
    if state.get("topic") and state.get("question"):
        # Список явно недопустимых команд в режиме вопроса
        invalid_commands = ["помощь", "help", "что делать", "правила", "инструкция"]

        if command in invalid_commands:
            response["response"]["text"] = (
                f"Вы находитесь в режиме вопроса по теме '{state['topic']}'. "
                f"Пожалуйста, выберите вариант ответа или скажите 'назад' для возврата в меню."
            )
            response["response"]["buttons"] = [{"title": "Назад в меню"}]
            # Сохраняем текущее состояние
            response["user_state_update"] = state
            return jsonify(response)

    # 5️⃣ Ответ на вопрос - проверяем user_state
    # 5️⃣ Ответ на вопрос - проверяем user_state
    if state.get("topic") and state.get("question"):
        topic = state["topic"]
        current_question = state["question"]
        previous_questions = state.get("previous_questions", [])

        # Нормализуем ответы для сравнения
        user_answers = parse_multiple_answers(command)  # Теперь получаем список ответов!
        correct_answers_normalized = normalize_correct_answers(current_question["Правильный"])

        # Проверяем правильность ответов
        if user_answers:
            # Проверяем какие ответы правильные, а какие нет
            correct_given = [ans for ans in user_answers if ans in correct_answers_normalized]
            incorrect_given = [ans for ans in user_answers if ans not in correct_answers_normalized]

            if not incorrect_given and set(user_answers) == set(correct_answers_normalized):
                # Все ответы правильные и выбраны все нужные
                text = f"✅ Верно! Вы выбрали все правильные варианты: {', '.join(current_question['Правильный'])}\n\n{current_question['Пояснение']}"
            elif not incorrect_given:
                # Все выбранные ответы правильные, но не все нужные выбраны
                missing = [ans for ans in correct_answers_normalized if ans not in user_answers]
                missing_text = ", ".join([f"{ans.upper()})" for ans in missing])
                text = f"✅ Частично верно! Вы выбрали правильные ответы, но не хватает: {missing_text}\n\n{current_question['Пояснение']}"
            else:
                # Есть неправильные ответы
                correct_text = ", ".join(current_question["Правильный"])
                incorrect_text = ", ".join([f"{ans.upper()})" for ans in incorrect_given])
                text = f"❌ Неверно. Неправильные варианты: {incorrect_text}\n\nПравильный ответ: {correct_text}\n\n{current_question['Пояснение']}"
        else:
            # Не распознано ни одного ответа
            correct_text = ", ".join(current_question["Правильный"])
            text = f"❌ Неверно.\n\nПравильный ответ: {correct_text}\n\n{current_question['Пояснение']}"

        # Следующий вопрос (остальное без изменений)
        next_question = get_random_question(topic, previous_questions)
        if next_question:
            options_text = "\n".join([f"{opt}" for opt in next_question["Варианты"]]) if next_question[
                "Варианты"] else ""
            text += (
                f"\n\nСледующий вопрос:\n{next_question['Вопрос']}\n\n"
                f"{options_text}"
            )
            updated_previous_questions = previous_questions + [next_question["Вопрос"]]
            response["user_state_update"] = {
                "topic": topic,
                "question": next_question,
                "previous_questions": updated_previous_questions
            }
        else:
            text += "\n\n🎉 Вопросы в этой теме закончились!"
            response["user_state_update"] = {}

        response["response"]["text"] = text
        response["response"]["buttons"] = [{"title": "Назад в меню"}]
        return jsonify(response)
    # 6️⃣ Если команда не распознана
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