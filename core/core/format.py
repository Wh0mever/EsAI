def format_errors(errors):
    formatted = {}
    for field, error_list in errors.items():
        if isinstance(error_list, list):
            formatted[field] = ' '.join([str(e) for e in error_list])
        else:
            formatted[field] = str(error_list)
    return formatted
