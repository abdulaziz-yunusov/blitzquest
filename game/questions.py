import random

def generate_math_question(difficulty="normal"):
    """
    Generates a random math question (addition, subtraction, multiplication) based on difficulty.

    Args:
        difficulty (str): "easy", "normal", or "hard".

    Returns:
        dict: A dictionary containing:
            - id (str): Unique question ID.
            - prompt (str): The question text (e.g., "What is 5 + 3?").
            - choices (list): List of 4 answer choices (strings).
            - correct_index (int): Index of the correct answer in the choices list.
    """
    if difficulty == "easy":
        a = random.randint(1, 12)
        b = random.randint(1, 12)
        ops = ["+", "-", "*"]
    elif difficulty == "hard":
        a = random.randint(10, 99)
        b = random.randint(10, 99)
        ops = ["+", "-", "*"]
    else:  # normal
        a = random.randint(1, 30)
        b = random.randint(1, 30)
        ops = ["+", "-", "*"]

    op = random.choice(ops)

    if op == "+":
        correct = a + b
    elif op == "-":
        correct = a - b
    else:
        correct = a * b

    correct_str = str(correct)

    wrongs = set()
    spread = 5 if difficulty == "easy" else (15 if difficulty == "normal" else 40)
    while len(wrongs) < 3:
        cand = correct + random.randint(-spread, spread)
        if cand != correct:
            wrongs.add(str(cand))

    choices = list(wrongs)[:3] + [correct_str]
    random.shuffle(choices)

    return {
        "id": f"q_{random.randint(100000, 999999)}",
        "prompt": f"What is {a} {op} {b}?",
        "choices": choices,
        "correct_index": choices.index(correct_str),
    }
