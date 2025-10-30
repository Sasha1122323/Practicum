from flask import Flask, request, jsonify
import openpyxl
import random
import re
import os
import logging
import json
from datetime import datetime

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

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
    matches = re.findall(r'([А-ЯЁA-Z]\))', str(correct_str))
    return matches


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


def normalize_answer(user_answer):
    if not user_answer:
        return ""
    user_answer = user_answer.strip().lower()
    digit_to_letter = {"1": "а", "2": "б", "3": "в", "4": "г", "5": "д", "6": "е"}
    if user_answer in digit_to_letter:
        return digit_to_letter[user_answer]
    user_answer = re.sub(r'[).\s]', '', user_answer)
    return user_answer[0] if user_answer else ""


def normalize_correct_answers(correct_answers):
    normalized = []
    for answer in correct_answers:
        clean_answer = re.sub(r'[)\s]', '', answer).lower()
        if clean_answer:
            normalized.append(clean_answer[0])
    return normalized


def parse_multiple_answers(command):
    """Парсит несколько ответов из одной команды"""
    cleaned = re.sub(r'[.,;]', ' ', command.lower())
    answers = cleaned.split()

    normalized_answers = []
    for answer in answers:
        normalized = normalize_answer(answer)
        if normalized and normalized in 'абвгдежзийклмнопрстуфхцчшщъыьэюя':
            normalized_answers.append(normalized)

    return normalized_answers


# ===============================
# 🚀 Основной Webhook
# ===============================
@app.route("/", methods=["POST"])
def main():
    try:
        req = request.json
        if not req:
            return jsonify_error("Пустой запрос")

        command = req["request"]["command"].strip().lower()
        session = req.get("session", {})

        # 🔴 ВАЖНО: получаем state из session
        state = req.get("state", {}).get("session", {})

        logger.info(f"Получен запрос: команда='{command}', session_id={session.get('session_id')}")

        response = {
            "version": req["version"],
            "session": req["session"],
            "response": {"end_session": False, "text": "", "buttons": []},
            "session_state": {}  # 🔴 ВАЖНО: используем session_state вместо user_state_update
        }

        # 1️⃣ Новая сессия — приветствие
        if session.get("new", False):
            buttons = [{"title": name} for name in sheet_names]
            response["response"]["text"] = "Привет! 👋 Выберите тему для тестирования:"
            response["response"]["buttons"] = buttons
            logger.info("Новая сессия: отправлено приветствие")
            return jsonify(response)

        # 2️⃣ Назад в меню
        if command in ["назад", "в меню", "меню", "главная"]:
            buttons = [{"title": name} for name in sheet_names]
            response["response"]["text"] = "Вы вернулись в главное меню. Выберите тему:"
            response["response"]["buttons"] = buttons
            response["session_state"] = {}  # 🔴 Очищаем состояние
            logger.info("Возврат в меню")
            return jsonify(response)

        # 3️⃣ Проверка выбора темы
        for sheet_name in sheet_names:
            if command == sheet_name.lower():
                topic = sheet_name
                question = get_random_question(topic)
                if not question:
                    response["response"]["text"] = f"В теме '{topic}' нет вопросов."
                    response["response"]["buttons"] = [{"title": "Назад в меню"}]
                    logger.warning(f"В теме '{topic}' нет вопросов")
                    return jsonify(response)

                options_text = "\n".join([f"{opt}" for opt in question["Варианты"]]) if question["Варианты"] else ""
                response_text = (
                    f'Тема: "{topic}"\n\n'
                    f'{question["Вопрос"]}\n\n'
                    f'{options_text}'
                )

                # Обрезаем если слишком длинный
                if len(response_text) > 1000:
                    response_text = response_text[:997] + "..."

                response["response"]["text"] = response_text
                response["response"]["buttons"] = [{"title": "Назад в меню"}]

                # 🔴 ВАЖНО: Сохраняем состояние в session_state
                response["session_state"] = {
                    "topic": topic,
                    "question": question,
                    "previous_questions": [question["Вопрос"]]
                }

                logger.info(f"Выбрана тема '{topic}'")
                return jsonify(response)

        # 4️⃣ Проверка на неизвестные команды в режиме вопроса
        if state.get("topic") and state.get("question"):
            # Если команда не является ответом (не цифра и не буква), обрабатываем как неизвестную
            normalized_command = normalize_answer(command)
            if not normalized_command or normalized_command not in 'абвгдежзийклмнопрстуфхцчшщъыьэюя':
                response["response"]["text"] = (
                    f"Вы находитесь в режиме вопроса по теме '{state['topic']}'. "
                    f"Пожалуйста, выберите вариант ответа или скажите 'назад' для возврата в меню."
                )
                response["response"]["buttons"] = [{"title": "Назад в меню"}]
                # Сохраняем текущее состояние
                response["session_state"] = state
                logger.info(f"Неизвестная команда в режиме вопроса: '{command}'")
                return jsonify(response)

        # 5️⃣ Ответ на вопрос
        if state.get("topic") and state.get("question"):
            topic = state["topic"]
            current_question = state["question"]
            previous_questions = state.get("previous_questions", [])

            user_answers = parse_multiple_answers(command)
            correct_answers_normalized = normalize_correct_answers(current_question["Правильный"])

            if user_answers:
                correct_given = [ans for ans in user_answers if ans in correct_answers_normalized]
                incorrect_given = [ans for ans in user_answers if ans not in correct_answers_normalized]

                if not incorrect_given and set(user_answers) == set(correct_answers_normalized):
                    text = f"✅ Верно! Вы выбрали все правильные варианты: {', '.join(current_question['Правильный'])}\n\n{current_question['Пояснение']}"
                    logger.info(f"Правильный ответ: {user_answers}")
                elif not incorrect_given:
                    missing = [ans for ans in correct_answers_normalized if ans not in user_answers]
                    missing_text = ", ".join([f"{ans.upper()})" for ans in missing])
                    text = f"✅ Частично верно! Вы выбрали правильные ответы, но не хватает: {missing_text}\n\n{current_question['Пояснение']}"
                    logger.info(f"Частично правильный ответ: {user_answers}, не хватает: {missing}")
                else:
                    correct_text = ", ".join(current_question["Правильный"])
                    incorrect_text = ", ".join([f"{ans.upper()})" for ans in incorrect_given])
                    text = f"❌ Неверно. Неправильные варианты: {incorrect_text}\n\nПравильный ответ: {correct_text}\n\n{current_question['Пояснение']}"
                    logger.info(f"Неправильный ответ: {user_answers}, правильные: {correct_answers_normalized}")
            else:
                correct_text = ", ".join(current_question["Правильный"])
                text = f"❌ Неверно.\n\nПравильный ответ: {correct_text}\n\n{current_question['Пояснение']}"
                logger.info(f"Не распознан ответ: '{command}'")

            # Следующий вопрос
            next_question = get_random_question(topic, previous_questions)
            if next_question:
                options_text = "\n".join([f"{opt}" for opt in next_question["Варианты"]]) if next_question[
                    "Варианты"] else ""
                text += (
                    f"\n\nСледующий вопрос:\n{next_question['Вопрос']}\n\n"
                    f"{options_text}"
                )
                # Обрезаем если слишком длинный
                if len(text) > 1000:
                    text = text[:997] + "..."

                # Обновляем историю вопросов
                updated_previous_questions = previous_questions + [next_question["Вопрос"]]
                response["session_state"] = {
                    "topic": topic,
                    "question": next_question,
                    "previous_questions": updated_previous_questions
                }
            else:
                text += "\n\n🎉 Вопросы в этой теме закончились!"
                response["session_state"] = {}

            response["response"]["text"] = text
            response["response"]["buttons"] = [{"title": "Назад в меню"}]
            return jsonify(response)

        # 6️⃣ Если команда не распознана
        buttons = [{"title": name} for name in sheet_names]
        response["response"]["text"] = "Пожалуйста, выберите тему из предложенных ниже 👇"
        response["response"]["buttons"] = buttons
        logger.info(f"Не распознана команда: '{command}'")
        return jsonify(response)

    except Exception as e:
        logger.error(f"Ошибка обработки запроса: {e}")
        return jsonify_error(f"Произошла ошибка. Пожалуйста, попробуйте еще раз.")


def jsonify_error(message):
    """Формирует ответ с ошибкой"""
    return jsonify({
        "version": "1.0",
        "response": {"text": message, "end_session": False},
        "session_state": {}  # 🔴 ВАЖНО: используем session_state
    })


@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "status": "success",
        "message": "Навык Алисы работает!",
        "topics_loaded": list(quizzes.keys()),
        "questions_count": {topic: len(questions) for topic, questions in quizzes.items()}
    })


@app.route("/health", methods=["GET"])
def health():
    """Эндпоинт для проверки здоровья приложения"""
    return jsonify({"status": "healthy", "timestamp": str(datetime.now())})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    logger.info(f"🚀 ЗАПУСК СЕРВЕРА НА ПОРТУ {port}")
    app.run(host="0.0.0.0", port=port, debug=False)