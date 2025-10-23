from flask import Flask, request, jsonify
import pandas as pd
import random

app = Flask(__name__)

# === Загружаем все листы Excel ===
excel_file = "questions.xlsx"
xls = pd.ExcelFile(excel_file)
questions_data = {}

for sheet in xls.sheet_names:
    df = pd.read_excel(excel_file, sheet_name=sheet)
    # Проверяем, что нужные столбцы есть
    if all(col in df.columns for col in ["Тема", "Вопрос", "Варианты", "Правильный ответ", "Пояснение"]):
        questions_data[sheet] = df.to_dict(orient="records")

print(f"✅ Загружены блоки: {list(questions_data.keys())}")

# Храним состояния пользователей
session_state = {}

@app.route("/", methods=["POST"])
def main():
    req = request.get_json()
    user_id = req["session"]["session_id"]
    command = req["request"]["command"].lower()
    user_state = session_state.setdefault(user_id, {"block": None, "question": None})

    # === Приветствие ===
    if "привет" in command or "начать" in command:
        block_list = "\n".join([f"{i+1}. {name}" for i, name in enumerate(questions_data.keys())])
        return make_response(
            f"Привет! Это тренировка по охране труда.\nВыберите блок:\n{block_list}"
        )

    # === Выбор блока ===
    if user_state["block"] is None:
        # Попробуем угадать, какой блок выбрал пользователь (по номеру или названию)
        chosen_block = None
        for i, name in enumerate(questions_data.keys()):
            if str(i + 1) in command or name.lower() in command:
                chosen_block = name
                break

        if not chosen_block:
            return make_response("Пожалуйста, выберите блок по номеру или названию.")

        user_state["block"] = chosen_block
        question = random.choice(questions_data[chosen_block])
        user_state["question"] = question

        variants = question["Варианты"].split(";")
        variants_text = "\n".join([f"{i+1}. {v.strip()}" for i, v in enumerate(variants)])

        return make_response(f"Тема: {question['Тема']}\n{question['Вопрос']}\n{variants_text}")

    # === Обработка ответа ===
    current_q = user_state["question"]
    if current_q:
        correct_answer = current_q["Правильный ответ"].strip().lower()
        variants = [v.strip().lower() for v in current_q["Варианты"].split(";")]

        # Команды пропуска
        if "пропустить" in command or "следующий" in command:
            next_question = random.choice(questions_data[user_state["block"]])
            user_state["question"] = next_question
            variants_text = "\n".join([f"{i+1}. {v.strip()}" for i, v in enumerate(next_question["Варианты"].split(";"))])
            return make_response(f"Следующий вопрос:\n{next_question['Вопрос']}\n{variants_text}")

        # Проверяем правильность
        if correct_answer in command or any(correct_answer in v for v in command.split()):
            text = "Верно! Следующий вопрос?"
        else:
            text = f"Неверно. Правильный ответ — {current_q['Правильный ответ']}. {current_q['Пояснение']}"

        # Задаём новый вопрос
        next_q = random.choice(questions_data[user_state["block"]])
        user_state["question"] = next_q
        variants_text = "\n".join([f"{i+1}. {v.strip()}" for i, v in enumerate(next_q["Варианты"].split(";"))])
        return make_response(f"{text}\n\nСледующий вопрос:\n{next_q['Вопрос']}\n{variants_text}")

    return make_response("Я вас не понял. Скажите 'начать', чтобы начать тренировку.")


def make_response(text, end_session=False):
    return jsonify({
        "response": {"text": text, "end_session": end_session},
        "version": "1.0"
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
