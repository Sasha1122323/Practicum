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


# ===============================
# 🚀 Основной Webhook С ДИАГНОСТИКОЙ
# ===============================
@app.route("/", methods=["POST"])
def main():
    # 🔴 ШАГ 1: ЗАПИСЫВАЕМ ВХОДЯЩИЙ ЗАПРОС
    logger.info("=" * 80)
    logger.info("🟢 ПОЛУЧЕН НОВЫЙ ЗАПРОС")
    logger.info("=" * 80)

    try:
        req = request.json
        logger.info("📥 ВХОДЯЩИЙ JSON:")
        logger.info(json.dumps(req, ensure_ascii=False, indent=2))

        if not req:
            logger.error("❌ ПУСТОЙ ЗАПРОС")
            return jsonify_error("Пустой запрос")

        command = req["request"]["command"].strip().lower()
        session = req.get("session", {})
        state = req.get("state", {})

        # 🔴 ШАГ 2: ДИАГНОСТИКА ВСЕХ ПОЛЕЙ
        logger.info("🔍 ДИАГНОСТИКА ПОЛЕЙ:")
        logger.info(f"   Команда: '{command}'")
        logger.info(f"   Session ID: {session.get('session_id')}")
        logger.info(f"   New session: {session.get('new')}")
        logger.info(f"   State keys: {list(state.keys())}")

        # Проверяем разные варианты state
        user_state = state.get("user", {})
        session_state = state.get("session", {})
        application_state = state.get("application", {})

        logger.info(f"   user_state: {user_state}")
        logger.info(f"   session_state: {session_state}")
        logger.info(f"   application_state: {application_state}")

        # 🔴 ШАГ 3: ПОДГОТОВКА ОТВЕТА
        response = {
            "version": req["version"],
            "session": req["session"],
            "response": {"end_session": False, "text": "", "buttons": []},
            "user_state_update": {}
        }

        # 1️⃣ Новая сессия — приветствие
        if session.get("new", False):
            logger.info("🎯 ОБРАБОТКА: Новая сессия")
            buttons = [{"title": name} for name in sheet_names]
            response["response"]["text"] = "Привет! 👋 Выберите тему для тестирования:"
            response["response"]["buttons"] = buttons
            logger.info("📤 ОТВЕТ: Приветствие с выбором тем")
            return jsonify(response)

        # 2️⃣ Назад в меню
        if command in ["назад", "в меню", "меню", "главная"]:
            logger.info("🎯 ОБРАБОТКА: Возврат в меню")
            buttons = [{"title": name} for name in sheet_names]
            response["response"]["text"] = "Вы вернулись в главное меню. Выберите тему:"
            response["response"]["buttons"] = buttons
            response["user_state_update"] = {}
            logger.info("📤 ОТВЕТ: Главное меню")
            return jsonify(response)

        # 3️⃣ Проверка выбора темы
        for sheet_name in sheet_names:
            if command == sheet_name.lower():
                logger.info(f"🎯 ОБРАБОТКА: Выбор темы '{sheet_name}'")
                topic = sheet_name
                question = get_random_question(topic)
                if not question:
                    response["response"]["text"] = f"В теме '{topic}' нет вопросов."
                    response["response"]["buttons"] = [{"title": "Назад в меню"}]
                    logger.warning(f"📤 ОТВЕТ: Нет вопросов в теме '{topic}'")
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

                # 🔴 ВАЖНО: Сохраняем состояние
                response["user_state_update"] = {
                    "topic": topic,
                    "question": question,
                    "previous_questions": [question["Вопрос"]]
                }

                logger.info(f"📤 ОТВЕТ: Вопрос по теме '{topic}'")
                logger.info(f"💾 СОХРАНЯЕМ STATE: topic={topic}, question_id={question['Вопрос'][:30]}...")
                return jsonify(response)

        # 🔴 ШАГ 4: ПРОВЕРЯЕМ СОСТОЯНИЕ ДЛЯ ОТВЕТА НА ВОПРОС
        logger.info("🔍 ПРОВЕРКА STATE ДЛЯ ОТВЕТА:")

        # Пробуем разные варианты state
        current_state = user_state  # сначала пробуем user
        state_source = "user_state"

        if not current_state.get("topic") or not current_state.get("question"):
            current_state = session_state  # пробуем session
            state_source = "session_state"

        if not current_state.get("topic") or not current_state.get("question"):
            current_state = application_state  # пробуем application
            state_source = "application_state"

        if not current_state.get("topic") or not current_state.get("question"):
            current_state = state  # пробуем корневой state
            state_source = "root_state"

        logger.info(f"   Используем state из: {state_source}")
        logger.info(f"   topic: {current_state.get('topic')}")
        logger.info(f"   has_question: {'question' in current_state}")

        # 4️⃣ Ответ на вопрос
        if current_state.get("topic") and current_state.get("question"):
            logger.info("🎯 ОБРАБОТКА: Ответ на вопрос")

            topic = current_state["topic"]
            current_question = current_state["question"]
            previous_questions = current_state.get("previous_questions", [])

            logger.info(f"   Тема: {topic}")
            logger.info(f"   Вопрос: {current_question['Вопрос'][:50]}...")
            logger.info(f"   Ответ пользователя: '{command}'")

            # Нормализуем ответы для сравнения
            user_answer_normalized = normalize_answer(command)
            correct_answers_normalized = normalize_correct_answers(current_question["Правильный"])

            logger.info(f"   Нормализованный ответ: '{user_answer_normalized}'")
            logger.info(f"   Правильные ответы: {correct_answers_normalized}")

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

                # Обновляем историю вопросов
                updated_previous_questions = previous_questions + [next_question["Вопрос"]]
                response["user_state_update"] = {
                    "topic": topic,
                    "question": next_question,
                    "previous_questions": updated_previous_questions
                }
                logger.info("💾 СОХРАНЯЕМ STATE: следующий вопрос")
            else:
                text += "\n\n🎉 Вопросы в этой теме закончились!"
                response["user_state_update"] = {}
                logger.info("💾 ОЧИЩАЕМ STATE: вопросы закончились")

            response["response"]["text"] = text
            response["response"]["buttons"] = [{"title": "Назад в меню"}]
            logger.info("📤 ОТВЕТ: Результат проверки ответа")
            return jsonify(response)
        else:
            logger.warning("❌ STATE НЕ НАЙДЕН: не могу обработать ответ на вопрос")

        # 5️⃣ Если команда не распознана
        logger.info("🎯 ОБРАБОТКА: Неизвестная команда")
        buttons = [{"title": name} for name in sheet_names]
        response["response"]["text"] = "Пожалуйста, выберите тему из предложенных ниже 👇"
        response["response"]["buttons"] = buttons
        logger.info("📤 ОТВЕТ: Предложение выбрать тему")
        return jsonify(response)

    except Exception as e:
        logger.error(f"💥 КРИТИЧЕСКАЯ ОШИБКА: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return jsonify_error(f"Произошла ошибка: {e}")


def jsonify_error(message):
    """Формирует ответ с ошибкой"""
    return jsonify({
        "version": "1.0",
        "response": {"text": message, "end_session": False},
        "user_state_update": {}
    })


@app.route("/", methods=["GET"])
def home():
    return "Навык Алисы работает! 🚀", 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    logger.info(f"🚀 ЗАПУСК СЕРВЕРА НА ПОРТУ {port}")
    app.run(host="0.0.0.0", port=port, debug=False)