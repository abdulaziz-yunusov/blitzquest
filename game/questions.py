import random

def generate_math_question():
    a = random.randint(1, 12)
    b = random.randint(1, 12)
    op = random.choice(["+", "-", "*"])

    if op == "+":
        correct = a + b
    elif op == "-":
        correct = a - b
    else:
        correct = a * b

    correct_str = str(correct)

    wrongs = set()
    while len(wrongs) < 3:
        wrongs.add(str(correct + random.randint(-5, 5)))

    choices = list(wrongs)[:3] + [correct_str]
    random.shuffle(choices)

    return {
        "id": f"q_{random.randint(100000, 999999)}",
        "prompt": f"What is {a} {op} {b}?",
        "choices": choices,
        "correct_index": choices.index(correct_str),
    }
