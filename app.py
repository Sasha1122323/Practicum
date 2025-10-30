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
    """Нормализует ответ, принимает только цифры 1-6 и буквы а-е"""
    if not user_answer:
        return ""

    user_answer = user_answer.strip().lower()

    # 🔥 ТОЛЬКО цифры 1-6
    digit_to_letter = {"1": "а", "2": "б", "3": "в", "4": "г", "5": "д", "6": "е"}
    if user_answer in digit_to_letter:
        return digit_to_letter[user_answer]

    # Удаляем скобки, точки, пробелы
    user_answer = re.sub(r'[).\s,]', '', user_answer)

    # 🔥 ТОЛЬКО первые 6 букв русского алфавита (а-е)
    if user_answer and user_answer[0] in 'абвгде':
        return user_answer[0]

    return ""


def normalize_correct_answers(correct_answers):
    normalized = []
    for answer in correct_answers:
        clean_answer = re.sub(r'[)\s]', '', answer).lower()
        if clean_answer and clean_answer[0] in 'абвгде':
            normalized.append(clean_answer[0])
    return normalized


def parse_multiple_answers(command):
    """Парсит несколько ответов, принимает только валидные цифры/буквы"""
    # Разделяем по пробелам, запятым, точкам
    cleaned = re.sub(r'[.,;]', ' ', command.lower())
    answers = cleaned.split()

    normalized_answers = []
    valid_answers = set()

    for answer in answers:
        normalized = normalize_answer(answer)
        # 🔥 Добавляем только если это валидный ответ и его еще нет
        if normalized and normalized not in valid_answers:
            normalized_answers.append(normalized)
            valid_answers.add(normalized)

    return normalized_answers


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
            "session_state": {}
        }

        # 1️⃣ Новая сессия — приветствие
        if session.get("new", False):
            user_sessions[session_id] = {}
            buttons = [{"title": name} for name in sheet_names]
            response["response"]["text"] = "Привет! 👋 Выберите тему для тестирования:"
            response["response"]["buttons"] = buttons
            logger.info("Новая сессия: отправлено приветствие")
            return jsonify(response)

        # 🔴 ВАЖНО: ПЕРВОЕ - проверка команд навигации
        # 2️⃣ Назад в меню (разные варианты команды)
        if any(nav_cmd in command for nav_cmd in ["назад", "меню", "главная", "выход"]):
            user_sessions[session_id] = {}
            buttons = [{"title": name} for name in sheet_names]
            response["response"]["text"] = "Вы вернулись в главное меню. Выберите тему:"
            response["response"]["buttons"] = buttons
            logger.info("Возврат в меню")
            return jsonify(response)

        # 3️⃣ Помощь
        if command in ["помощь", "help", "что делать", "правила"]:
            if user_state.get("mode") == "question":
                response["response"]["text"] = (
                    f"Вы в режиме вопроса по теме '{user_state['topic']}'. "
                    f"Произнесите номер ответа (1-6) или букву (А-Е). "
                    f"Можно несколько ответов через пробел: '1 2' или 'а б'. "
                    f"Или скажите 'назад' для возврата в меню."
                )
            else:
                response["response"]["text"] = (
                    "Я помогу вам подготовиться к экзамену! "
                    "Выберите тему для тестирования или скажите 'назад' в любой момент."
                )
            response["response"]["buttons"] = [{"title": "Назад в меню"}]
            logger.info("Показана помощь")
            return jsonify(response)

        # 4️⃣ Проверка выбора темы
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

                if len(response_text) > 1000:
                    response_text = response_text[:997] + "..."

                response["response"]["text"] = response_text
                response["response"]["buttons"] = [{"title": "Назад в меню"}]

                # 🔥 СОХРАНЯЕМ СОСТОЯНИЕ
                user_sessions[session_id] = {
                    "topic": topic,
                    "question": question,
                    "previous_questions": [question["Вопрос"]],
                    "mode": "question"
                }

                logger.info(f"Выбрана тема '{topic}', сохранено состояние")
                return jsonify(response)

        # 5️⃣ Ответ на вопрос - проверяем наше состояние
        if user_state.get("mode") == "question" and user_state.get("topic") and user_state.get("question"):
            topic = user_state["topic"]
            current_question = user_state["question"]
            previous_questions = user_state.get("previous_questions", [])

            logger.info(f"Обрабатываем ответ для темы '{topic}': '{command}'")

            # 🔥 Парсим ответы
            user_answers = parse_multiple_answers(command)
            correct_answers_normalized = normalize_correct_answers(current_question["Правильный"])

            logger.info(f"Распознанные ответы: {user_answers}")
            logger.info(f"Правильные ответы: {correct_answers_normalized}")

            # Проверяем - если ответ не распознан как валидный
            if not user_answers:
                response["response"]["text"] = (
                    f"Не понял ответ '{command}'. "
                    f"Используйте цифры 1-6 или буквы А-Е. "
                    f"Пример: '1', 'а', '1 2', 'а б'. "
                    f"Или скажите 'назад' для возврата в меню."
                )
                response["response"]["buttons"] = [{"title": "Назад в меню"}]
                user_sessions[session_id] = user_state
                logger.info(f"Невалидный ответ: '{command}'")
                return jsonify(response)

            # 🔥 ПРОВЕРКА ПРАВИЛЬНОСТИ ОТВЕТА - ИСПРАВЛЕННАЯ ЛОГИКА
            correct_given = [ans for ans in user_answers if ans in correct_answers_normalized]
            incorrect_given = [ans for ans in user_answers if ans not in correct_answers_normalized]

            logger.info(f"Правильные из ответов: {correct_given}")
            logger.info(f"Неправильные из ответов: {incorrect_given}")

            # 🔥 ВАЖНО: Проверяем по отдельности каждый случай
            if not incorrect_given and len(correct_given) == len(correct_answers_normalized):
                # 🔥 ВСЕ ответы правильные и выбраны ВСЕ нужные
                logger.info("✅ ВСЕ ОТВЕТЫ ПРАВИЛЬНЫЕ")
                text = f"✅ Верно! Вы выбрали все правильные варианты."
            elif not incorrect_given and len(correct_given) > 0:
                # 🔥 ВЫБРАНЫ ТОЛЬКО ПРАВИЛЬНЫЕ ответы, но не все
                logger.info("🟡 ЧАСТИЧНО ПРАВИЛЬНЫЙ - выбраны только правильные")
                missing = [ans for ans in correct_answers_normalized if ans not in user_answers]
                missing_text = ", ".join([f"{ans.upper()})" for ans in missing])
                text = f"✅ Частично верно! Вы выбрали правильные ответы, но не хватает: {missing_text}"
            elif len(correct_given) > 0 and len(incorrect_given) > 0:
                # 🔥 ЕСТЬ И ПРАВИЛЬНЫЕ И НЕПРАВИЛЬНЫЕ ответы
                logger.info("🟡 СМЕШАННЫЙ ОТВЕТ - есть и правильные и неправильные")
                correct_text = ", ".join([f"{ans.upper()})" for ans in correct_given])
                incorrect_text = ", ".join([f"{ans.upper()})" for ans in incorrect_given])
                all_correct_text = ", ".join(current_question["Правильный"])
                text = f"🟡 Частично верно! Правильные: {correct_text}, неправильные: {incorrect_text}\nПолностью правильный ответ: {all_correct_text}"
            else:
                # 🔥 ВСЕ ответы неправильные
                logger.info("❌ ВСЕ ОТВЕТЫ НЕПРАВИЛЬНЫЕ")
                correct_text = ", ".join(current_question["Правильный"])
                text = f"❌ Неверно.\nПравильный ответ: {correct_text}"

            # 🔥 СЛЕДУЮЩИЙ ВОПРОС (ВСЕГДА, кроме случая когда вопросы закончились)
            next_question = get_random_question(topic, previous_questions)
            if next_question:
                options_text = "\n".join([f"{opt}" for opt in next_question["Варианты"]]) if next_question[
                    "Варианты"] else ""
                text += (
                    f"\n\nСледующий вопрос:\n{next_question['Вопрос']}\n\n"
                    f"{options_text}"
                )
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
                user_sessions[session_id] = {}
                logger.info("Вопросы закончились, состояние очищено")

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
        import traceback
        logger.error(traceback.format_exc())
        return jsonify_error(f"Произошла ошибка. Пожалуйста, попробуйте еще раз.")


def jsonify_error(message):
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


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    logger.info(f"🚀 ЗАПУСК СЕРВЕРА НА ПОРТУ {port}")
    app.run(host="0.0.0.0", port=port, debug=False)