import sys
from math import ceil


def print_menu(title, options):
    print(f"\n{title}\n")
    for i, opt in enumerate(options, 1):
        print(f"[{i}] {opt}")
    print("[A] Todas")
    print("[B] Volver")
    print("[Q] Salir\n")


def select_multiple(options):
    choice = input("Seleccioná opciones (ej: 1,3 o A): ").strip().lower()

    if choice == "q":
        sys.exit(0)
    if choice == "b":
        return None
    if choice == "a":
        return options

    selected = []
    for part in choice.split(","):
        part = part.strip()
        if part.isdigit():
            idx = int(part) - 1
            if 0 <= idx < len(options):
                selected.append(options[idx])

    return selected if selected else []


def print_columns(options, cols=3):
    rows = ceil(len(options) / cols)
    grid = [options[i * rows:(i + 1) * rows] for i in range(cols)]

    print()
    idx = 1
    index_map = {}

    for r in range(rows):
        row_items = []
        for c in range(cols):
            if r < len(grid[c]):
                label = f"[{idx}] {grid[c][r]}"
                index_map[str(idx)] = grid[c][r]
                row_items.append(label.ljust(30))
                idx += 1
        print("".join(row_items))

    print("\n[A] Todas   [B] Volver   [Q] Salir\n")
    return index_map


def select_from_columns(options):
    index_map = print_columns(options)

    choice = input("Seleccioná opciones (ej: 1,3 o A): ").strip().lower()

    if choice == "q":
        sys.exit(0)
    if choice == "b":
        return None
    if choice == "a":
        return options

    selected = []
    for part in choice.split(","):
        part = part.strip()
        if part in index_map:
            selected.append(index_map[part])

    return selected if selected else []
