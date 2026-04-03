def clean_numbers(values):
    cleaned = []
    for value in values:
        if value != None and str(value).strip() != "":
            cleaned.append(int(str(value).strip()))
    return cleaned
