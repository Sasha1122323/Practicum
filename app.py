from flask import Flask, request, jsonify
import openpyxl
import random
import re
import os
import logging
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


def get_random_question(topic, previous_questions=None):
    if topic not in quizzes or not quizzes[topic]:
        return None

    if previous_questions is None:
        previous_questions = []

    available_questions = [q for q in quizzes[topic] if q["Вопрос"] not in previous_questions]

    if not available_questions:
        available_questions = quizzes[topic]

    return random.choice(available_questions)


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


# 🔥 ВРЕМЕННОЕ ХРАНИЛИЩЕ ДЛЯ СЕССИЙ
user_sessions = {}


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
        session_id = session.get("session_id")

        logger.info(f"Получен запрос: команда='{command}', session_id={session_id}")

        # 🔥 ПОЛУЧАЕМ СОСТОЯНИЕ ИЗ НАШЕГО ХРАНИЛИЩА
        user_state = user_sessions.get(session_id, {})

        response = {
            "version": req["version"],
            "session": req["session"],
            "response": {"end_session": False, "text": "", "buttons": []},
            "session_state": {}  # Пустой, т.к. используем свое хранилище
        }

        # 1️⃣ Новая сессия — приветствие
        if session.get("new", False):
            # Очищаем состояние для новой сессии
            user_sessions[session_id] = {}
            buttons = [{"title": name} for name in sheet_names]
            response["response"]["text"] = "Привет! 👋 Выберите тему для тестирования:"
            response["response"]["buttons"] = buttons
            logger.info("Новая сессия: отправлено приветствие")
            return jsonify(response)

        # 2️⃣ Назад в меню
        if command in ["назад", "в меню", "меню", "главная"]:
            # Очищаем состояние
            user_sessions[session_id] = {}
            buttons = [{"title": name} for name in sheet_names]
            response["response"]["text"] = "Вы вернулись в главное меню. Выберите тему:"
            response["response"]["buttons"] = buttons
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

                # 🔥 СОХРАНЯЕМ СОСТОЯНИЕ В НАШЕ ХРАНИЛИЩЕ
                user_sessions[session_id] = {
                    "topic": topic,
                    "question": question,
                    "previous_questions": [question["Вопрос"]],
                    "mode": "question"
                }

                logger.info(f"Выбрана тема '{topic}', сохранено состояние")
                return jsonify(response)

        # 4️⃣ Ответ на вопрос - проверяем наше состояние
        if user_state.get("mode") == "question" and user_state.get("topic") and user_state.get("question"):
            topic = user_state["topic"]
            current_question = user_state["question"]
            previous_questions = user_state.get("previous_questions", [])

            logger.info(f"Обрабатываем ответ для темы '{topic}'")

            # Нормализуем ответы для сравнения
            user_answer_normalized = normalize_answer(command)
            correct_answers_normalized = normalize_correct_answers(current_question["Правильный"])

            # Проверяем правильность ответа
            if user_answer_normalized in correct_answers_normalized:
                logger.info("✅ ОТВЕТ ПРАВИЛЬНЫЙ")
                if len(correct_answers_normalized) > 1:
                    remaining_answers = [ans for ans in correct_answers_normalized if ans != user_answer_normalized]
                    if remaining_answers:
                        remaining_text = ", ".join([f"{ans.upper()})" for ans in remaining_answers])
                        text = f"✅ Частично верно! Вы выбрали правильный ответ {user_answer_normalized.upper()}), но есть еще правильные варианты: {remaining_text}\n\n{current_question['Пояснение']}"
                    else:
                        text = f"✅ Верно!\n\n{current_question['Пояснение']}"
                else:
                    text = f"✅ Верно!\n\n{current_question['Пояснение']}"
            else:
                logger.info("❌ ОТВЕТ НЕПРАВИЛЬНЫЙ")
                correct_text = ", ".join(current_question["Правильный"])
                text = f"❌ Неверно.\n\nПравильный ответ: {correct_text}\n\n{current_question['Пояснение']}"

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

                # 🔥 ОБНОВЛЯЕМ СОСТОЯНИЕ
                updated_previous_questions = previous_questions + [next_question["Вопрос"]]
                user_sessions[session_id] = {
                    "topic": topic,
                    "question": next_question,
                    "previous_questions": updated_previous_questions,
                    "mode": "question"
                }
                logger.info("Сохранен следующий вопрос")
            else:
                text += "\n\n🎉 Вопросы в этой теме закончились!"
                # Очищаем состояние
                user_sessions[session_id] = {}
                logger.info("Вопросы закончились, состояние очищено")

            response["response"]["text"] = text
            response["response"]["buttons"] = [{"title": "Назад в меню"}]
            return jsonify(response)

        # 5️⃣ Если команда не распознана и мы в режиме вопроса
        if user_state.get("mode") == "question":
            response["response"]["text"] = (
                f"Вы находитесь в режиме вопроса по теме '{user_state['topic']}'. "
                f"Пожалуйста, выберите вариант ответа (1, 2, 3 или А, Б, В) или скажите 'назад' для возврата в меню."
            )
            response["response"]["buttons"] = [{"title": "Назад в меню"}]
            logger.info(f"Неизвестная команда в режиме вопроса: '{command}'")
            return jsonify(response)

        # 6️⃣ Если команда не распознана (главное меню)
        buttons = [{"title": name} for name in sheet_names]
        response["response"]["text"] = "Пожалуйста, выберите тему из предложенных ниже 👇"
        response["response"]["buttons"] = buttons
        logger.info(f"Не распознана команда: '{command}'")
        return jsonify(response)

    except Exception as e:
        logger.error(f"Ошибка обработки запроса: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return jsonify_error(f"Произошла ошибка. Пожалуйста, попробуйте еще раз.")


def jsonify_error(message):
    """Формирует ответ с ошибкой"""
    return jsonify({
        "version": "1.0",
        "response": {"text": message, "end_session": False},
        "session_state": {}
    })


@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "status": "success",
        "message": "Навык Алисы работает!",
        "active_sessions": len(user_sessions),
        "topics_loaded": list(quizzes.keys())
    })


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "healthy", "timestamp": str(datetime.now())})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    logger.info(f"🚀 ЗАПУСК СЕРВЕРА НА ПОРТУ {port}")
    app.run(host="0.0.0.0", port=port, debug=False)