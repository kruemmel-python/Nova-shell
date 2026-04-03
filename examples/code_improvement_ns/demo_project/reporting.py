def render_total(values):
    total = 0
    for value in values:
        total += value
    return f"total={total}"
